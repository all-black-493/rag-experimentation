from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_anthropic import ChatAnthropic
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from app.api.routes import catalog, graph, query
from app.caching import TTLCache, enable_llm_cache
from app.config import get_settings
from app.graph.store import ensure_citation_collection, load_graph
from app.proxy_auth import require_proxy_secret
from app.rate_limit import limiter
from app.resilience import CircuitBreaker
from app.retrieval.catalog import CatalogHolder
from app.retrieval.graph import build_graph
from app.retrieval.pairwise import PairwiseReranker
from app.retrieval.reranker import build_reranker, warm_reranker
from app.tracing import configure_tracing, shutdown_tracing
from app.vectorstore.client import weaviate_client
from app.vectorstore.embeddings import build_embeddings, warm_embeddings
from app.vectorstore.schema import ensure_collections


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_tracing(settings)
    if settings.llm_cache_enabled:
        enable_llm_cache()

    embeddings = build_embeddings(settings)
    reranker = build_reranker(settings)
    # Load both local models before serving, so the first query after a deploy
    # doesn't pay for them inside the request.
    warm_reranker(settings)
    warm_embeddings(settings)
    pairwise = (
        PairwiseReranker(settings.pairwise_model, settings.pairwise_max_candidates)
        if settings.pairwise_rerank_enabled
        else None
    )
    llm = ChatAnthropic(
        model=settings.generation_model,
        anthropic_api_key=settings.anthropic_api_key,
        timeout=settings.external_timeout_seconds,
        max_retries=settings.external_max_retries,
    )
    planner = ChatAnthropic(
        model=settings.planner_model,
        anthropic_api_key=settings.anthropic_api_key,
        timeout=settings.external_timeout_seconds,
        max_retries=settings.external_max_retries,
    )
    # Same model, no cache: a cached verdict would pin one sampled judgment on
    # one answer forever, which is how a good answer was declined every time.
    verifier = llm.model_copy(update={"cache": False})
    rerank_breaker = CircuitBreaker(
        "rerank",
        failure_threshold=settings.circuit_breaker_failures,
        reset_seconds=settings.circuit_breaker_reset_seconds,
    )

    with weaviate_client(settings) as client:
        ensure_collections(client)
        # Rebuilt on a TTL, so an ingest in another process shows up without a
        # restart. Built once here so the first request doesn't pay for it.
        catalog = CatalogHolder(client, settings.catalog_refresh_seconds)
        catalog.current()
        app.state.catalog = catalog
        # The citation graph is derived data built by `python -m app.graph.build`;
        # loaded into memory here so a lookup during a request costs nothing.
        ensure_citation_collection(client)
        citation_graph = load_graph(client)
        app.state.citation_graph = citation_graph
        app.state.graph = build_graph(
            client=client,
            embeddings=embeddings,
            reranker=reranker,
            llm=llm,
            catalog=catalog,
            settings=settings,
            citation_graph=citation_graph,
            planner=planner,
            verifier=verifier,
            rerank_breaker=rerank_breaker,
            retrieval_cache=TTLCache(settings.retrieval_cache_ttl_seconds),
            plan_cache=TTLCache(settings.retrieval_cache_ttl_seconds),
            pairwise=pairwise,
        )
        try:
            yield
        finally:
            # Spans are buffered; without this a shutdown drops whatever hasn't
            # been sent yet.
            shutdown_tracing()


app = FastAPI(title="Kenya Law RAG API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIASGIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(query.router)
app.include_router(catalog.router)
app.include_router(graph.router)


@app.get("/health")
@limiter.exempt
def health() -> dict[str, str]:
    return {"status": "ok"}


# Registered last so it runs first: nothing above is reachable without the
# secret, when one is configured.
app.middleware("http")(require_proxy_secret)
