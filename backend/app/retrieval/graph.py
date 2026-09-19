"""The retrieval graph, wired.

    plan → retrieve → expand → rerank → [search] END
                                      → [ask]    generate → verify → END / decline

Every node lives in its own module; this file only connects them and binds
their dependencies. Mode is decided per request and routes after reranking:
search stops at ranked passages, ask goes on to a grounded answer.
"""

from functools import partial
from typing import Literal

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from weaviate.classes.query import HybridFusion
from weaviate.client import WeaviateClient

from app.caching import TTLCache
from app.config import Settings
from app.graph.store import Graph
from app.matters.store import MatterStore
from app.resilience import CircuitBreaker
from app.retrieval.answer import decline, generate, verify
from app.retrieval.catalog import CatalogHolder
from app.retrieval.expand import expand
from app.retrieval.pairwise import PairwiseReranker
from app.retrieval.planner import plan
from app.retrieval.rerank import rerank
from app.retrieval.reranker import Reranker
from app.retrieval.retrieve import retrieve
from app.retrieval.state import GraphState

# Weaviate's two fusion strategies for combining BM25 and vector rankings.
# RANKED is reciprocal rank fusion; RELATIVE_SCORE normalises and blends the
# underlying scores. See the note on Settings.hybrid_fusion for which wins here.
HYBRID_FUSIONS = {
    "relative": HybridFusion.RELATIVE_SCORE,
    "ranked": HybridFusion.RANKED,
}


def route_after_rerank(state: GraphState) -> Literal["answer", "search", "decline"]:
    if state["mode"] == "search":
        return "search"
    return "answer" if state["documents"] else "decline"


def route_after_verify(state: GraphState) -> Literal["grounded", "ungrounded"]:
    return "grounded" if state["grounded"] else "ungrounded"


def build_graph(
    *,
    client: WeaviateClient,
    embeddings: Embeddings,
    reranker: Reranker,
    llm: BaseChatModel,
    catalog: CatalogHolder,
    settings: Settings,
    citation_graph: Graph | None = None,
    planner: BaseChatModel | None = None,
    verifier: BaseChatModel | None = None,
    rerank_breaker: CircuitBreaker | None = None,
    retrieval_cache: TTLCache | None = None,
    plan_cache: TTLCache | None = None,
    matters: MatterStore | None = None,
    pairwise: PairwiseReranker | None = None,
) -> CompiledStateGraph:
    graph = StateGraph(GraphState)
    graph.add_node(
        "plan",
        partial(
            plan,
            # A small fast model: planning is routing, not reasoning.
            llm=planner or llm,
            catalog=catalog.current,
            max_subqueries=settings.planner_max_subqueries,
            enabled=settings.planner_enabled,
            cache=plan_cache,
            matters=matters,
        ),
    )
    graph.add_node(
        "retrieve",
        partial(
            retrieve,
            client=client,
            embeddings=embeddings,
            k=settings.retrieval_candidates,
            alpha=settings.hybrid_alpha,
            fusion=HYBRID_FUSIONS[settings.hybrid_fusion],
            min_candidates=settings.min_candidates_per_subquery,
            cache=retrieval_cache,
        ),
    )
    graph.add_node(
        "expand",
        partial(
            expand,
            client=client,
            embeddings=embeddings,
            graph=citation_graph or Graph(),
            alpha=settings.hybrid_alpha,
            fusion=HYBRID_FUSIONS[settings.hybrid_fusion],
            max_lookup_passages=settings.graph_max_lookup_passages,
            max_neighbours=settings.graph_max_neighbours,
            budget=settings.graph_candidate_budget,
            enabled=settings.graph_expansion_enabled,
        ),
    )
    graph.add_node(
        "rerank",
        partial(
            rerank,
            reranker=reranker,
            relevance_threshold=settings.rerank_relevance_threshold,
            keep={"ask": settings.rerank_top_n, "search": settings.search_results},
            breaker=rerank_breaker,
            pairwise=pairwise,
        ),
    )
    graph.add_node("generate", partial(generate, llm=llm))
    # The verifier judges sampled text and must not be served from cache; see
    # answer.verify. Defaults to the generator only for tests.
    graph.add_node("verify", partial(verify, llm=verifier or llm))
    graph.add_node("decline", decline)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "expand")
    graph.add_edge("expand", "rerank")
    graph.add_conditional_edges(
        "rerank",
        route_after_rerank,
        {"answer": "generate", "search": END, "decline": "decline"},
    )
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify", route_after_verify, {"grounded": END, "ungrounded": "decline"}
    )
    graph.add_edge("decline", END)

    return graph.compile()
