"""Re-score the pooled candidates against the original question.

The sub-queries were the planner's paraphrases; the reranker judges relevance
to what the user actually asked. It also decides how many survive: a grounded
answer wants a handful of precise passages, a search wants a longer list to
read through.
"""

import logging

from langchain_core.documents import Document

from app.resilience import CircuitBreaker, CircuitOpenError
from app.retrieval.pairwise import PairwiseReranker
from app.retrieval.reranker import Reranker
from app.retrieval.state import GraphState, Mode
from app.retrieval.tracing import traceable
from app.tracing import observation

logger = logging.getLogger(__name__)

# Named for the stage, not the vendor: the reranker is pluggable, and a span
# labelled with the wrong provider is worse than an unlabelled one.
RERANK_SPAN_NAME = "rerank-cross-encoder"


def _identity(doc: Document) -> tuple:
    """Match a reranked copy back to the candidate it came from."""
    return (doc.metadata.get("url"), doc.metadata.get("chunk_index"))


def rerank(
    state: GraphState,
    reranker: Reranker,
    *,
    relevance_threshold: float,
    keep: dict[Mode, int],
    breaker: CircuitBreaker | None = None,
    pairwise: PairwiseReranker | None = None,
) -> dict:
    candidates = state["documents"]
    limit = keep[state["mode"]]

    with observation(
        as_type="retriever",
        name=RERANK_SPAN_NAME,
        input={
            "question": state["question"],
            # Ordering in, so the reordering is visible against what came out.
            "candidates": [
                {"position": i, **traceable(doc)} for i, doc in enumerate(candidates, start=1)
            ],
        },
        metadata={"relevance_threshold": relevance_threshold, "keep": limit},
    ) as span:
        try:
            if breaker is not None:
                breaker.before_call()
            reranked = reranker.compress_documents(candidates, state["question"])
            if breaker is not None:
                breaker.record_success()
        except Exception as exc:  # noqa: BLE001 - any provider failure degrades the same way
            # Degrade rather than fail: hybrid search already ordered these by
            # relevance, so answering from an unreranked top slice beats refusing
            # to answer at all. The threshold can't be applied without scores.
            if breaker is not None and not isinstance(exc, CircuitOpenError):
                breaker.record_failure()
            logger.warning("rerank unavailable (%s); using retrieval order", exc)
            fallback = candidates[:limit]
            span.update(
                output=[traceable(doc) for doc in fallback],
                metadata={"reranked": False, "reason": str(exc)},
            )
            return {"documents": fallback}

        relevant = [
            doc
            for doc in reranked
            if doc.metadata.get("relevance_score", 0.0) >= relevance_threshold
        ][:limit]

        # Stage 3, over the finalists only. Failure here degrades to stage 2's
        # ordering rather than failing the query: a refinement that can't run is
        # not a reason to lose an answer.
        if pairwise is not None and relevant:
            try:
                relevant = pairwise.rerank(relevant, state["question"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("pairwise rerank unavailable (%s); keeping stage-2 order", exc)

        # Where each survivor sat before reranking, so a reorder is legible at a
        # glance. Keyed by identity rather than object: compress_documents
        # returns copies.
        original_position = {_identity(doc): i for i, doc in enumerate(candidates, start=1)}
        span.update(
            output=[
                {
                    "position": i,
                    "moved_from": original_position.get(_identity(doc)),
                    "relevance_score": doc.metadata.get("relevance_score"),
                    **traceable(doc),
                }
                for i, doc in enumerate(relevant, start=1)
            ],
            metadata={
                "candidates": len(candidates),
                "kept": len(relevant),
                "dropped_below_threshold": len(reranked) - len(relevant),
                "pairwise": pairwise is not None,
            },
        )
        return {"documents": relevant}
