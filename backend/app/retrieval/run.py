"""One query, end to end, under one trace.

Both API routes - the JSON one and the streaming one - run the same graph, apply
the same citation enforcement, and record the same scores on the trace. This
module is that shared path, so the two can never drift apart on what an answer
means.

Everything here is synchronous and self-contained on purpose: the routes hand
it to a worker thread, and the active-observation context is thread-local, so
the root span has to be opened on the same thread the graph nodes run on.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.retrieval.citations import Citation, build_citations
from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan
from app.retrieval.state import GraphState, Mode, SubQueryResult
from app.scoring import citation_coverage, strip_invalid_citations
from app.tracing import build_callback_handler, trace

logger = logging.getLogger(__name__)


@dataclass
class QueryOutcome:
    mode: Mode
    question: str
    plan: QueryPlan | None = None
    retrieval: list[SubQueryResult] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    # Ask mode only.
    answer: str | None = None
    grounded: bool | None = None


@dataclass(frozen=True)
class StreamEvent:
    """One server-sent event: `plan`, `sources`, `token`, `done` or `error`."""

    event: str
    data: Any


def initial_state(question: str, mode: Mode, filters: LegalFilters) -> GraphState:
    return {
        "question": question,
        "mode": mode,
        "user_filters": filters,
        "documents": [],
        "answer": "",
        "grounded": False,
    }


def _finalize(state: GraphState, mode: Mode, question: str, root) -> QueryOutcome:
    """Enforce the citation contract and score the trace.

    A marker pointing past the context is a reference the reader can't check, so
    it is removed before the answer leaves the server - not just measured.
    """
    documents = state["documents"]
    outcome = QueryOutcome(
        mode=mode,
        question=question,
        plan=state.get("plan"),
        retrieval=state.get("retrieval", []),
        citations=build_citations(documents),
    )
    metadata: dict = {
        "mode": mode,
        "plan_origin": outcome.plan.origin if outcome.plan else None,
        "sub_queries": len(outcome.plan.sub_queries) if outcome.plan else 0,
        "relaxed": sum(1 for r in outcome.retrieval if r["relaxed"]),
    }

    if mode == "search":
        root.update(output={"passages": len(documents)}, metadata=metadata)
        root.score_trace(name="answered", value=bool(documents), data_type="BOOLEAN")
        return outcome

    answered = bool(documents)
    cleaned, stripped = strip_invalid_citations(state["answer"], len(documents))
    if stripped:
        logger.warning("stripped invalid citation markers %s", stripped)
    outcome.answer = cleaned
    outcome.grounded = bool(state.get("grounded"))
    report = citation_coverage(cleaned, len(documents))

    root.update(
        output={"answer": cleaned, "citations": len(documents)},
        metadata={
            **metadata,
            "grounded": outcome.grounded,
            "declined": not answered,
            "cited_indices": report.cited_indices,
            "unused_citations": report.unused_citations,
            "invalid_indices": stripped,
        },
    )
    # Scores rather than metadata: these are the series tracked over time, and
    # Langfuse aggregates scores, not metadata.
    root.score_trace(name="answered", value=answered, data_type="BOOLEAN")
    if answered:
        root.score_trace(name="citation_coverage", value=report.coverage, data_type="NUMERIC")
        root.score_trace(name="grounded", value=outcome.grounded, data_type="BOOLEAN")
        # A marker pointing at a citation that doesn't exist is the model
        # inventing a reference, which coverage alone would score as a hit.
        root.score_trace(
            name="invalid_citations", value=float(len(stripped)), data_type="NUMERIC"
        )
    return outcome


def run_query(
    graph: CompiledStateGraph, question: str, mode: Mode, filters: LegalFilters
) -> QueryOutcome:
    with trace(name="rag-query", session_id=mode, input={"question": question}) as root:
        handler = build_callback_handler()
        config = {"callbacks": [handler]} if handler else {}
        try:
            state = graph.invoke(initial_state(question, mode, filters), config=config)
        except Exception:
            # An errored request would otherwise leave a trace with no scores at
            # all, which reads the same as a trace that was never sent.
            root.score_trace(name="failed", value=True, data_type="BOOLEAN")
            raise
        root.score_trace(name="failed", value=False, data_type="BOOLEAN")
        return _finalize(state, mode, question, root)


def stream_query(
    graph: CompiledStateGraph, question: str, mode: Mode, filters: LegalFilters
) -> Iterator[StreamEvent]:
    """The same run, surfaced as it happens.

    Node outputs arrive as `updates`; generation tokens as `messages`, filtered
    to the generate node so the planner's and verifier's own model calls don't
    leak into the answer. The final `done` carries the finalized outcome - the
    streamed tokens are a preview, the outcome is authoritative.
    """
    with trace(name="rag-query", session_id=mode, input={"question": question}) as root:
        handler = build_callback_handler()
        config = {"callbacks": [handler]} if handler else {}
        state = initial_state(question, mode, filters)
        try:
            for kind, payload in graph.stream(
                state, config=config, stream_mode=["updates", "messages"]
            ):
                if kind == "updates":
                    for node, update in payload.items():
                        state.update(update)
                        if node == "plan":
                            yield StreamEvent("plan", _plan_payload(state))
                        elif node == "rerank":
                            yield StreamEvent(
                                "sources", {"citations": build_citations(state["documents"])}
                            )
                elif kind == "messages":
                    chunk, metadata = payload
                    if metadata.get("langgraph_node") == "generate" and chunk.text:
                        yield StreamEvent("token", {"text": chunk.text})
        except Exception as exc:
            root.score_trace(name="failed", value=True, data_type="BOOLEAN")
            logger.exception("query stream failed")
            yield StreamEvent("error", {"detail": str(exc)})
            return
        root.score_trace(name="failed", value=False, data_type="BOOLEAN")
        yield StreamEvent("done", _finalize(state, mode, question, root))


def _plan_payload(state: GraphState) -> dict:
    plan = state.get("plan")
    return {"plan": plan.model_dump() if plan else None}
