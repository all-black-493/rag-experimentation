import logging
from functools import partial
from typing import Literal

from langchain_cohere import CohereRerank
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_weaviate import WeaviateVectorStore
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from weaviate.classes.query import HybridFusion
from weaviate.client import WeaviateClient

from app.caching import TTLCache
from app.resilience import CircuitBreaker, CircuitOpenError
from app.retrieval.citations import format_context
from app.retrieval.filters import build_filter
from app.retrieval.grounding import DECLINE_MESSAGE, VERIFY_PROMPT, GroundednessCheck
from app.retrieval.prompts import GENERATION_PROMPT
from app.retrieval.state import GraphState
from app.tracing import linked_prompt, observation
from app.vectorstore.store import tenant_exists

logger = logging.getLogger(__name__)

# Weaviate's two fusion strategies for combining BM25 and vector rankings.
# RANKED is reciprocal rank fusion; RELATIVE_SCORE normalises and blends the
# underlying scores. See the note on Settings.hybrid_fusion for which wins here.
HYBRID_FUSIONS = {
    "relative": HybridFusion.RELATIVE_SCORE,
    "ranked": HybridFusion.RANKED,
}

# How many hybrid-search results to keep when the reranker is unavailable.
_RERANK_FALLBACK_TOP_N = 5


def _identity(doc: Document) -> tuple:
    """Match a reranked copy back to the candidate it came from."""
    return (doc.page_content, doc.metadata.get("doc_id"), doc.metadata.get("page"))


def _traceable(doc: Document) -> dict:
    """One chunk as it should read in a trace: full text plus its provenance."""
    return {
        "source": doc.metadata.get("source"),
        "title": doc.metadata.get("title"),
        "source_type": doc.metadata.get("source_type"),
        "page": doc.metadata.get("page"),
        "doc_id": doc.metadata.get("doc_id"),
        "text": doc.page_content,
    }


def retrieve(
    state: GraphState,
    vector_store: WeaviateVectorStore,
    client: WeaviateClient,
    collection: str,
    k: int,
    alpha: float,
    cache: TTLCache | None = None,
    fusion: object | None = None,
) -> dict:
    tenant = state["tenant"]
    # Named for the operation, not the node: LangGraph's callback already emits a
    # span called "retrieve", and two same-named spans read as a duplicate.
    with observation(
        as_type="retriever",
        name="weaviate-hybrid-search",
        input={"question": state["question"]},
        metadata={
            "k": k,
            "hybrid_alpha": alpha,
            "collection": collection,
            "filters": state.get("filters").describe() if state.get("filters") else None,
        },
    ) as span:
        # Tenant is part of the key, so a cache hit can only ever return the
        # asking session's own documents.
        filters = state.get("filters")
        weaviate_filter = build_filter(filters) if filters is not None else None
        # Filters are part of the identity of a result set; without them in the
        # key an unfiltered answer would be served to a filtered query.
        cache_key = TTLCache.key(
            tenant, state["question"], k, alpha, collection,
            repr(filters.describe()) if filters is not None else "",
        )
        if cache is not None:
            hit = cache.get(cache_key)
            if hit is not None:
                span.update(
                    output=[_traceable(doc) for doc in hit],
                    metadata={"cached": True, "retrieved": len(hit)},
                )
                return {"documents": hit}

        if not tenant_exists(client, collection, tenant):
            span.update(output=[], metadata={"tenant_exists": False})
            return {"documents": []}

        search_kwargs = {"k": k, "alpha": alpha, "tenant": tenant}
        if fusion is not None:
            search_kwargs["fusion_type"] = fusion
        if weaviate_filter is not None:
            search_kwargs["filters"] = weaviate_filter
        documents = vector_store.similarity_search(state["question"], **search_kwargs)
        if cache is not None:
            cache.set(cache_key, documents, namespace=tenant)
        span.update(
            output=[_traceable(doc) for doc in documents],
            metadata={"tenant_exists": True, "retrieved": len(documents), "cached": False},
        )
        return {"documents": documents}


def rerank(
    state: GraphState,
    reranker: CohereRerank,
    relevance_threshold: float,
    breaker: CircuitBreaker | None = None,
) -> dict:
    candidates = state["documents"]
    with observation(
        as_type="retriever",
        name="cohere-rerank",
        input={
            "question": state["question"],
            # Ordering in, so the reordering is visible against what came out.
            "candidates": [
                {"position": i, **_traceable(doc)} for i, doc in enumerate(candidates, start=1)
            ],
        },
        metadata={"relevance_threshold": relevance_threshold},
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
            fallback = candidates[:_RERANK_FALLBACK_TOP_N]
            span.update(
                output=[_traceable(doc) for doc in fallback],
                metadata={"reranked": False, "reason": str(exc)},
            )
            return {"documents": fallback}

        relevant = [
            doc
            for doc in reranked
            if doc.metadata.get("relevance_score", 0.0) >= relevance_threshold
        ]

        # Where each survivor sat before reranking, so a reorder is legible at a
        # glance rather than by eyeballing two lists side by side. Keyed by content
        # rather than identity: compress_documents returns copies, not the originals.
        original_position = {_identity(doc): i for i, doc in enumerate(candidates, start=1)}
        span.update(
            output=[
                {
                    "position": i,
                    "moved_from": original_position.get(_identity(doc)),
                    "relevance_score": doc.metadata.get("relevance_score"),
                    **_traceable(doc),
                }
                for i, doc in enumerate(relevant, start=1)
            ],
            metadata={
                "candidates": len(candidates),
                "kept": len(relevant),
                "dropped_below_threshold": len(reranked) - len(relevant),
            },
        )
        return {"documents": relevant}


def route_after_rerank(state: GraphState) -> Literal["generate", "decline"]:
    return "generate" if state["documents"] else "decline"


def _prompt_metadata(prompt) -> dict:
    """Tag the LLM call with the prompt revision that produced it.

    Rides along on the invoke config so it lands on the generation itself - the
    callback handler captures the rendered messages but has no idea which
    versioned template in prompts/ they came from.
    """
    return {"metadata": {"prompt": prompt.name, "prompt_version": prompt.version}}


def generate(state: GraphState, llm: BaseChatModel) -> dict:
    # No wrapping span here: LangGraph's callback already emits one named after
    # this node, and a second identically-named span just doubles the tree.
    context = format_context(state["documents"])
    message = GENERATION_PROMPT.template.invoke(
        {"context": context, "question": state["question"]}
    )
    with linked_prompt(GENERATION_PROMPT.name):
        response = llm.invoke(message, config=_prompt_metadata(GENERATION_PROMPT))
    # .text (not .content) because content can be a list of blocks - e.g. Claude's
    # adaptive thinking, on by default, adds a thinking block alongside the text one.
    return {"answer": response.text}


def verify(state: GraphState, llm: BaseChatModel) -> dict:
    # "evaluator" rather than a plain span: this call judges another call's output,
    # which is what that observation type is for.
    with observation(
        as_type="evaluator",
        name="verify-groundedness",
        input={"question": state["question"], "answer": state["answer"]},
        metadata={"prompt": VERIFY_PROMPT.name, "prompt_version": VERIFY_PROMPT.version},
    ) as span:
        checker = llm.with_structured_output(GroundednessCheck)
        context = format_context(state["documents"])
        message = VERIFY_PROMPT.template.invoke(
            {"context": context, "question": state["question"], "answer": state["answer"]}
        )
        with linked_prompt(VERIFY_PROMPT.name):
            result: GroundednessCheck = checker.invoke(
                message, config=_prompt_metadata(VERIFY_PROMPT)
            )
        span.update(output={"grounded": result.grounded})
        return {"grounded": result.grounded}


def route_after_verify(state: GraphState) -> Literal["grounded", "ungrounded"]:
    return "grounded" if state["grounded"] else "ungrounded"


def decline(state: GraphState) -> dict:
    return {"answer": DECLINE_MESSAGE, "documents": []}


def build_graph(
    vector_store: WeaviateVectorStore,
    client: WeaviateClient,
    reranker: CohereRerank,
    llm: BaseChatModel,
    *,
    collection: str,
    retrieval_candidates: int,
    hybrid_alpha: float,
    relevance_threshold: float,
    rerank_breaker: CircuitBreaker | None = None,
    retrieval_cache: TTLCache | None = None,
    fusion: object | None = None,
) -> CompiledStateGraph:
    graph = StateGraph(GraphState)
    graph.add_node(
        "retrieve",
        partial(
            retrieve,
            vector_store=vector_store,
            client=client,
            collection=collection,
            k=retrieval_candidates,
            alpha=hybrid_alpha,
            cache=retrieval_cache,
            fusion=fusion,
        ),
    )
    graph.add_node(
        "rerank",
        partial(
            rerank,
            reranker=reranker,
            relevance_threshold=relevance_threshold,
            breaker=rerank_breaker,
        ),
    )
    graph.add_node("generate", partial(generate, llm=llm))
    graph.add_node("verify", partial(verify, llm=llm))
    graph.add_node("decline", decline)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_conditional_edges(
        "rerank", route_after_rerank, {"generate": "generate", "decline": "decline"}
    )
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify", route_after_verify, {"grounded": END, "ungrounded": "decline"}
    )
    graph.add_edge("decline", END)

    return graph.compile()
