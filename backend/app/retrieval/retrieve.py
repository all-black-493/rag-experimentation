"""Run the plan: one hybrid search per sub-query, merged into one candidate pool.

The user's own words are always searched too, once per collection the plan
touches. Measured, not assumed: on the golden set a plain hybrid search with the
original question scored 100% recall@5 and the planner's paraphrases alone
97.2% - a rewrite loses the exact wording keyword search matches on. Adding the
original back makes the plan pure expansion: it can find more, never less.

Sequential rather than parallel on purpose. Each sub-query is one local
embedding (~15ms) and one Weaviate round trip, so four of them cost well under
a second - and the trace stays honest, because the active span lives in
thread-local context and nested observations opened on worker threads would
not attach to the request's trace.
"""

import logging

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from weaviate.classes.query import HybridFusion
from weaviate.client import WeaviateClient

from app.caching import TTLCache
from app.retrieval.filters import LegalFilters, build_filter, merge
from app.retrieval.plan import SubQuery
from app.retrieval.state import GraphState, SubQueryResult
from app.retrieval.tracing import traceable
from app.tracing import observation
from app.vectorstore.search import hybrid_search

logger = logging.getLogger(__name__)


def _identity(doc: Document) -> tuple:
    return (doc.metadata.get("url"), doc.metadata.get("chunk_index"))


def _search(
    client: WeaviateClient,
    embeddings: Embeddings,
    sub: SubQuery,
    filters: LegalFilters,
    *,
    k: int,
    alpha: float,
    fusion: HybridFusion,
    cache: TTLCache | None,
) -> list[Document]:
    # Filters are part of a result set's identity: without them in the key, an
    # unfiltered answer would be served to a filtered query.
    key = TTLCache.key(sub.collection, sub.query, repr(filters.describe()), k, alpha)
    if cache is not None and (hit := cache.get(key)) is not None:
        return hit

    documents = hybrid_search(
        client,
        sub.collection,
        sub.query,
        embeddings.embed_query(sub.query),
        alpha=alpha,
        fusion=fusion,
        limit=k,
        filters=build_filter(filters, sub.collection),
    )
    if cache is not None:
        cache.set(key, documents)
    return documents


def retrieve(
    state: GraphState,
    client: WeaviateClient,
    embeddings: Embeddings,
    *,
    k: int,
    alpha: float,
    fusion: HybridFusion,
    min_candidates: int,
    cache: TTLCache | None = None,
) -> dict:
    plan = state["plan"]
    user = state["user_filters"]

    pooled: dict[tuple, Document] = {}
    results: list[SubQueryResult] = []
    for sub in _with_original(plan.sub_queries, state["question"]):
        effective = merge(user, sub.filters())
        with observation(
            as_type="retriever",
            name="weaviate-hybrid-search",
            input={"query": sub.query, "collection": sub.collection},
            metadata={"k": k, "hybrid_alpha": alpha, "filters": effective.narrowing()},
        ) as span:
            applied = effective
            documents = _search(
                client, embeddings, sub, applied, k=k, alpha=alpha, fusion=fusion, cache=cache
            )
            # The planner's restriction was too narrow to fill a pool worth
            # reranking. The user's own filters are kept - those are a promise,
            # not a guess.
            relaxed = len(documents) < min_candidates and effective.narrows_beyond(user)
            if relaxed:
                applied = user
                documents = _search(
                    client, embeddings, sub, applied, k=k, alpha=alpha, fusion=fusion, cache=cache
                )
            span.update(
                output=[traceable(doc) for doc in documents],
                metadata={"retrieved": len(documents), "relaxed": relaxed},
            )

        results.append(
            SubQueryResult(
                query=sub.query,
                collection=sub.collection,
                filters=applied.narrowing(),
                retrieved=len(documents),
                relaxed=relaxed,
            )
        )
        # First occurrence wins: a chunk two sub-queries both found keeps the
        # position the earlier one gave it. The reranker re-scores everything
        # against the original question anyway.
        for doc in documents:
            pooled.setdefault(_identity(doc), doc)

    return {"documents": list(pooled.values()), "retrieval": results}


def _with_original(sub_queries: list[SubQuery], question: str) -> list[SubQuery]:
    """The plan's sub-queries plus the question verbatim, per collection touched."""
    searches = list(sub_queries)
    for collection in dict.fromkeys(sub.collection for sub in sub_queries):
        if not any(s.collection == collection and s.query == question for s in searches):
            searches.append(SubQuery(query=question, collection=collection))
    return searches
