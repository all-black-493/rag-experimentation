from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from langchain_anthropic import ChatAnthropic
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from app.api.routes import favicons, files, ingestion, query, thumbnails
from app.caching import TTLCache, enable_llm_cache
from app.config import get_settings
from app.jobs import JobRegistry
from app.rate_limit import limiter
from app.resilience import CircuitBreaker
from app.retrieval.graph import build_graph
from app.retrieval.reranker import build_reranker
from app.tracing import configure_tracing, shutdown_tracing
from app.vectorstore.client import weaviate_client
from app.vectorstore.embeddings import build_embeddings
from app.vectorstore.store import build_vector_store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_tracing(settings)
    if settings.llm_cache_enabled:
        enable_llm_cache()

    embeddings = build_embeddings(settings)
    reranker = build_reranker(settings)
    llm = ChatAnthropic(
        model=settings.generation_model,
        anthropic_api_key=settings.anthropic_api_key,
        timeout=settings.external_timeout_seconds,
        max_retries=settings.external_max_retries,
    )
    rerank_breaker = CircuitBreaker(
        "cohere-rerank",
        failure_threshold=settings.circuit_breaker_failures,
        reset_seconds=settings.circuit_breaker_reset_seconds,
    )

    with weaviate_client(settings) as client:
        vector_store = build_vector_store(client, embeddings, settings)

        app.state.vector_store = vector_store
        retrieval_cache = TTLCache(settings.retrieval_cache_ttl_seconds)
        app.state.retrieval_cache = retrieval_cache
        app.state.jobs = JobRegistry(max_concurrency=settings.ingest_concurrency)
        app.state.graph = build_graph(
            vector_store,
            client,
            reranker,
            llm,
            collection=settings.weaviate_collection,
            retrieval_candidates=settings.retrieval_candidates,
            hybrid_alpha=settings.hybrid_alpha,
            relevance_threshold=settings.rerank_relevance_threshold,
            rerank_breaker=rerank_breaker,
            retrieval_cache=retrieval_cache,
        )

        try:
            yield
        finally:
            # Spans are buffered; without this a shutdown drops whatever hasn't
            # been sent yet.
            shutdown_tracing()


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="RAG API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIASGIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(ingestion.router)
app.include_router(query.router)
app.include_router(files.router)
app.include_router(favicons.router)
app.include_router(thumbnails.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# The frontend is served with an ETag but no Cache-Control, which leaves browsers
# free to apply heuristic caching and skip revalidation entirely. Across a deploy
# that means a returning visitor can end up mixing a fresh app.js with a cached
# api.js and land on a page whose halves disagree - which is exactly how the
# hover previews broke during development. "no-cache" still permits caching, it
# just requires revalidating first, so the ETag keeps unchanged files at a cheap
# 304 rather than a re-download.
_REVALIDATE_PREFIXES = ("/vendor/", "/recoleta/")


@app.middleware("http")
async def revalidate_frontend_assets(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    is_frontend_asset = path == "/" or path.endswith((".js", ".css", ".html"))
    # Vendored libraries and fonts are version-pinned by filename, so they can
    # stay immutable in cache.
    if is_frontend_asset and not path.startswith(_REVALIDATE_PREFIXES):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.frontend("/", directory=FRONTEND_DIR)
