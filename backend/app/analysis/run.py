"""The case analysis, step by step, each step reported as it lands.

Deterministic steps first - the documents, the authorities they cite, the
chronology - then the model-driven ones: what each document says, what the
matter turns on, the report. A model step that fails is recorded as a
warning and the analysis stands on what the rest produced; a lawyer with
the authorities and the chronology and no report is better off than one
with nothing.
"""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from weaviate.client import WeaviateClient

from app.analysis.authorities import find_authorities
from app.analysis.chronology import order_events
from app.analysis.chunks import load_chunks
from app.analysis.extract import anchored, extract_document
from app.analysis.models import CaseAnalysis
from app.analysis.resolve import CorpusResolver
from app.analysis.sources import SourceBook
from app.analysis.synthesise import synthesise, write_report
from app.graph.store import Graph
from app.matters.store import MatterStore

logger = logging.getLogger(__name__)

Emit = Callable[[str, Any], None]


def analyse(
    store: MatterStore,
    client: WeaviateClient,
    graph: Graph,
    llm: BaseChatModel | None,
    matter_id: str,
    emit: Emit,
) -> CaseAnalysis:
    matter = store.get(matter_id)
    if matter is None:
        raise KeyError(matter_id)
    names = {d.doc_id: d.name for d in matter.documents if d.status == "indexed"}
    analysis = CaseAnalysis(matter_id=matter_id)
    book = SourceBook()

    emit("step", {"name": "documents", "status": "started"})
    chunks = {doc_id: c for doc_id, c in load_chunks(client, matter_id).items() if doc_id in names}
    if not chunks:
        raise ValueError("the matter has no indexed documents")
    emit("step", {"name": "documents", "status": "done", "count": len(chunks)})

    emit("step", {"name": "authorities", "status": "started"})
    analysis.authorities = find_authorities(chunks, CorpusResolver(client), graph, book)
    analysis.sources = book.citations()
    emit("authorities", {"authorities": [a.model_dump() for a in analysis.authorities]})
    emit("step", {"name": "authorities", "status": "done", "count": len(analysis.authorities)})

    emit("step", {"name": "extract", "status": "started", "count": len(chunks)})
    events = []
    unread: dict[str, list[str]] = {}
    for doc_id, document_chunks in chunks.items():
        name = names[doc_id]
        if llm is None:
            unread.setdefault("no model available to read it", []).append(name)
            continue
        try:
            extraction = extract_document(llm, name, document_chunks)
        except Exception as exc:  # noqa: BLE001 - recorded on the analysis, the rest proceeds
            logger.warning("extraction failed for %s: %s", name, exc)
            unread.setdefault(_short(exc), []).append(name)
            continue
        parties, facts, doc_events, issues = anchored(extraction, document_chunks, book)
        analysis.parties.extend(
            p for p in parties if p.name.lower() not in {q.name.lower() for q in analysis.parties}
        )
        analysis.facts.extend(facts)
        analysis.issues.extend(issues)
        events.extend(doc_events)
        emit("step", {"name": "extract", "status": "progress", "document": name})
    for reason, documents in unread.items():
        analysis.warnings.append(f"{', '.join(documents)}: could not be read ({reason})")
    analysis.sources = book.citations()
    emit("parties", {"parties": [p.model_dump() for p in analysis.parties]})
    emit("facts", {"facts": [f.model_dump() for f in analysis.facts]})
    emit("step", {"name": "extract", "status": "done", "count": len(analysis.facts)})

    emit("step", {"name": "chronology", "status": "started"})
    analysis.chronology = order_events(events)
    emit("chronology", {"chronology": [e.model_dump() for e in analysis.chronology]})
    emit("step", {"name": "chronology", "status": "done", "count": len(analysis.chronology)})

    if llm is not None and analysis.facts:
        emit("step", {"name": "synthesis", "status": "started"})
        try:
            synthesis = synthesise(llm, analysis)
            analysis.issues = synthesis.issues or analysis.issues
            analysis.contradictions = synthesis.contradictions
            analysis.research_questions = synthesis.research_questions
            emit("step", {"name": "synthesis", "status": "done"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("synthesis failed: %s", exc)
            analysis.warnings.append(f"issues and contradictions: not analysed ({_short(exc)})")
            emit("step", {"name": "synthesis", "status": "failed", "detail": _short(exc)})
        emit("issues", {"issues": [i.model_dump() for i in analysis.issues]})
        emit(
            "contradictions", {"contradictions": [c.model_dump() for c in analysis.contradictions]}
        )
        emit("questions", {"questions": [q.model_dump() for q in analysis.research_questions]})

        emit("step", {"name": "report", "status": "started"})
        try:
            analysis.report = write_report(llm, analysis)
            emit("report", {"report": analysis.report})
            emit("step", {"name": "report", "status": "done"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("report failed: %s", exc)
            analysis.warnings.append(f"report: not written ({_short(exc)})")
            emit("step", {"name": "report", "status": "failed", "detail": _short(exc)})
    else:
        analysis.warnings.append(
            "issues, contradictions and the report need a model to read the documents"
            if llm is None
            else "no document could be read, so there are no issues, contradictions or report"
        )
        for name in ("synthesis", "report"):
            emit("step", {"name": name, "status": "skipped"})

    store.set_analysis(matter_id, analysis)
    return analysis


def _short(exc: Exception) -> str:
    from app.retrieval.run import failure_detail

    return failure_detail(exc)
