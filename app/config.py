from functools import lru_cache
from typing import Literal

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

    # Small-to-big: child_chunk_size_tokens is the unit that gets embedded and
    # matched, and whose bbox a citation highlights. parent_window_radius
    # neighbours either side form the window the model actually reads, so the
    # effective context per citation is roughly child * (2 * radius + 1).
    chunk_size_tokens: int = 650
    chunk_overlap_tokens: int = 250
    child_chunk_size_tokens: int = 200
    parent_window_radius: int = 1

    # Hybrid retrieval: alpha blends Weaviate's native BM25 + vector search
    # (0 = pure keyword, 1 = pure vector). retrieval_candidates is the pool
    # size fetched before reranking narrows it down.
    retrieval_candidates: int = 60
    hybrid_alpha: float = 0.5
    # How BM25 and vector rankings are combined. "relative" (Weaviate's default
    # relativeScoreFusion) normalises and blends the scores; "ranked" is
    # reciprocal rank fusion, which uses ranks only and ignores magnitude.
    #
    # Measured, don't assume: on eval/retrieval_benchmark.py over a 142-chunk
    # corpus, RRF scored 91.8% recall@1 against relative's 95.9%, and was behind
    # on MRR at every cutoff. RRF's score-scale independence is the right
    # instinct for combining unrelated retrievers, but here BM25 is the noisier
    # of the two and RRF gives its ranking equal standing with the vector
    # ranking's. Re-measure on real data before changing this.
    hybrid_fusion: Literal["relative", "ranked"] = "relative"

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

    # How many documents index at once. Bounded because the embedding provider
    # is rate-limited: more parallelism here buys 429s and retry backoff, not
    # throughput.
    ingest_concurrency: int = 2

    # Malware scanning. Off by default: ClamAV's signature database makes the
    # image heavy and slow to become ready. When on, an unreachable scanner
    # rejects the upload rather than passing it through.
    malware_scan_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0

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
