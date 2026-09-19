"""Widen the candidate pool with what the citation graph knows.

Two moves, both bounded and both leaving the reranker as the judge:

1. **Lookup.** If the question itself names an authority - "cases that applied
   Kaingu Elias Kasono v Republic", "section 8 of the Sexual Offences Act" -
   the passages that cite it are pulled in directly, each at the exact chunk
   where the citation sits. Vector search finds passages *about* a topic; this
   finds passages that *cite a thing*, which is a different question.
2. **Neighbours.** When the planner flagged the question as relational, the
   documents one hop from the top candidates contribute their best passage.

Every added passage is tagged with why it is there, so a citation can say
"cites Kaingu Elias Kasono v Republic" rather than appearing from nowhere.
The user's restrictions still hold: a passage the graph knows about but the
user has excluded - the wrong court, the wrong years - is not added.

The graph's own work is microseconds; what costs is every passage it adds
going through the cross-encoder. So the pool handed on never grows past a
budget: graph passages displace the weakest hybrid candidates instead.
"""

import re

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from weaviate.classes.query import Filter, HybridFusion
from weaviate.client import WeaviateClient

from app.graph.refs import extract_references, parties_key
from app.graph.store import Graph, Neighbour
from app.retrieval.filters import build_filter
from app.retrieval.state import GraphState
from app.retrieval.tracing import traceable
from app.tracing import observation
from app.vectorstore.search import fetch_chunk, hybrid_search

# "X v Y" in a question, for lookups by party name without a formal citation.
_PARTIES_IN_QUESTION = re.compile(
    r"([A-Z][\w'’&.\-]*(?:\s+[A-Z][\w'’&.\-]*){0,5})\s+v\.?\s+([A-Z][\w'’&.\-]*(?:\s+[A-Z][\w'’&.\-]*){0,5})"
)
# The answer is a set of documents: "which judgments have applied X". A
# question that merely mentions citing ("what did counsel argue, citing X")
# is about one document and must not widen.
_RELATIONAL_ASK = re.compile(
    r"\b(?:which|what)\s+(?:other\s+)?(?:cases?|judgments?|decisions?|authorities|courts?|rulings?)\b",
    re.IGNORECASE,
)


def looks_relational(question: str) -> bool:
    """A no-model fallback for the planner's `relationships` flag."""
    return bool(_RELATIONAL_ASK.search(question))


def _identity(doc: Document) -> tuple:
    return (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))


def lookups_for(question: str, graph: Graph) -> list[tuple[str, list[Neighbour]]]:
    """Citing passages for every authority the question names."""
    found: list[tuple[str, list[Neighbour]]] = []
    for ref in extract_references(question):
        passages = graph.citing_passages(ref.key, ref.provision)
        # A section nobody cited exactly may still be an Act many apply.
        if not passages and ref.provision:
            passages = graph.citing_passages(ref.key)
        if not passages and ref.parties:
            passages = graph.citing_passages(parties_key(ref.parties))
        if passages:
            found.append((ref.text, passages))
    if not found:
        for m in _PARTIES_IN_QUESTION.finditer(question):
            passages = graph.citing_passages(parties_key(m.group(0)))
            if passages:
                found.append((m.group(0), passages))
    return found


def expand(
    state: GraphState,
    client: WeaviateClient,
    embeddings: Embeddings,
    graph: Graph,
    *,
    alpha: float,
    fusion: HybridFusion,
    max_lookup_passages: int,
    max_neighbours: int,
    budget: int,
    enabled: bool = True,
) -> dict:
    if not enabled:
        return {"expansion": None}
    question = state["question"]
    user = state["user_filters"]
    plan = state.get("plan")
    planned = plan is not None and plan.origin == "planner"
    relational = plan.relationships if planned else looks_relational(question)
    pooled: dict[tuple, Document] = {_identity(d): d for d in state["documents"]}
    summary = {"lookups": [], "neighbours": 0, "added": 0}

    with observation(
        as_type="retriever",
        name="citation-graph-expand",
        input={"question": question, "relational": relational},
    ) as span:
        for cited, passages in lookups_for(question, graph):
            added = 0
            for n in passages[:max_lookup_passages]:
                if not user.allows(n.collection):
                    continue
                via = f"{'applies' if n.kind == 'applies' else 'cites'} {cited}"
                # Search may already have found the citing passage; it still
                # deserves to say why it answers the question.
                present = pooled.get((n.via_doc_id, n.via_chunk_index))
                if present is not None:
                    present.metadata.setdefault("via", via)
                    continue
                doc = fetch_chunk(client, n.collection, n.via_doc_id, n.via_chunk_index)
                if doc is None or _identity(doc) in pooled or not user.admits(doc.metadata):
                    continue
                doc.metadata["via"] = via
                pooled[_identity(doc)] = doc
                added += 1
            summary["lookups"].append({"cited": cited, "passages": len(passages), "added": added})
            summary["added"] += added

        if relational:
            vector = embeddings.embed_query(question)
            seen_docs: set[str] = set()
            for candidate in state["documents"][:5]:
                for n in graph.neighbours(candidate.metadata.get("doc_id", "")):
                    if n.doc_id in seen_docs or len(seen_docs) >= max_neighbours:
                        continue
                    if not user.allows(n.collection):
                        continue
                    seen_docs.add(n.doc_id)
                    within = Filter.by_property("doc_id").equal(n.doc_id)
                    if (restriction := build_filter(user, n.collection)) is not None:
                        within = within & restriction
                    best = hybrid_search(
                        client,
                        n.collection,
                        question,
                        vector,
                        alpha=alpha,
                        fusion=fusion,
                        limit=1,
                        filters=within,
                    )
                    for doc in best:
                        if _identity(doc) not in pooled:
                            doc.metadata["via"] = f"{n.kind} {n.ref}"
                            pooled[_identity(doc)] = doc
                            summary["added"] += 1
            summary["neighbours"] = len(seen_docs)

        documents = _within_budget(list(pooled.values()), len(state["documents"]), budget)
        span.update(
            output=[traceable(d) for d in documents if d.metadata.get("via")],
            metadata=summary,
        )
    return {"documents": documents, "expansion": summary}


def _within_budget(documents: list[Document], originals: int, budget: int) -> list[Document]:
    """Keep the pool at max(its original size, budget) by dropping the weakest originals."""
    added = documents[originals:]
    room = max(originals, budget) - len(added)
    if not added or room >= originals:
        return documents
    ranked = sorted(
        documents[:originals], key=lambda d: d.metadata.get("hybrid_score") or 0.0, reverse=True
    )
    kept = {_identity(d) for d in ranked[:room]}
    return [d for d in documents[:originals] if _identity(d) in kept] + added
