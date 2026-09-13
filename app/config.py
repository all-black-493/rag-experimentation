from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    weaviate_host: str = "localhost"
    weaviate_port: int = 8080
    weaviate_grpc_port: int = 50051
    weaviate_collection: str = "Chunk"

    cohere_api_key: str = ""
    embedding_model: str = "embed-v4.0"

    anthropic_api_key: str = ""
    generation_model: str = "claude-sonnet-5"

    chunk_size_tokens: int = 650
    chunk_overlap_tokens: int = 100

    # Hybrid retrieval: alpha blends Weaviate's native BM25 + vector search
    # (0 = pure keyword, 1 = pure vector). retrieval_candidates is the pool
    # size fetched before reranking narrows it down.
    retrieval_candidates: int = 60
    hybrid_alpha: float = 0.5

    # Cross-encoder reranking over the candidate pool. Cast a wide net and cut it
    # down hard: recall is cheap at the retrieval stage and precision is what the
    # generator actually needs, so a large candidate pool feeding a small, firmly
    # thresholded top_n beats retrieving narrowly and keeping most of it.
    rerank_model: str = "rerank-v3.5"
    rerank_top_n: int = 5
    rerank_relevance_threshold: float = 0.35

    # Anonymous access has no auth, so these bound abuse per session/IP instead.
    rate_limit_ingest: str = "20/minute"
    rate_limit_query: str = "30/minute"

    max_upload_size_mb: int = 20

    # Resilience for outbound provider calls. Bounded on purpose: an unbounded
    # retry against a rate-limited provider turns one slow request into a stalled
    # worker, which is how the ingestion hangs in this project started.
    external_timeout_seconds: float = 60.0
    external_max_retries: int = 3
    circuit_breaker_failures: int = 5
    circuit_breaker_reset_seconds: float = 30.0

    # Caches. Embeddings are content-addressed on disk; retrieval is per-tenant
    # and short-lived; the LLM cache is process-local.
    embedding_cache_enabled: bool = True
    retrieval_cache_ttl_seconds: float = 300.0
    llm_cache_enabled: bool = True

    # Langfuse tracing. Absent keys disable tracing entirely rather than erroring,
    # so local runs and CI never need a Langfuse project.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
