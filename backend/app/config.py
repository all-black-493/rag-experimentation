from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    weaviate_host: str = "localhost"
    weaviate_port: int = 8080
    weaviate_grpc_port: int = 50051

    cohere_api_key: str = ""
    embedding_model: str = "embed-v4.0"
    # "local" runs sentence-transformers in-process; "cohere" calls the hosted
    # API. Local by default: every ingest and query needs an embedding, so a
    # provider quota is a hard dependency for the whole pipeline.
    #
    # Changing this invalidates the index. Vectors from different models have
    # different dimensionality and geometry, so everything must be re-ingested.
    embedding_provider: Literal["local", "cohere"] = "local"
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"
    # BGE models are trained asymmetrically: queries carry this instruction,
    # passages do not. Omitting it silently costs retrieval quality.
    local_embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "

    # Who answers. "anthropic" pairs the generation model with the planner
    # model below; "ollama" runs local models (see app.llm) and costs nothing
    # per call, which is what lets every step be measured.
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"

    anthropic_api_key: str = ""
    generation_model: str = "claude-sonnet-5"
    # Planning is routing and decomposition, not reasoning: a small fast model
    # does it in a fraction of the time. Measured: the planner was 7s of a 23s
    # request on the generation model.
    planner_model: str = "claude-haiku-4-5-20251001"

    # Ollama. The app talks to the compose service by default; point it at a
    # host install with OLLAMA_BASE_URL=http://host.docker.internal:11434.
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:8b"
    ollama_fast_model: str = "qwen3:8b"
    ollama_num_ctx: int = 16384
    # Output caps. A local model at 2 tokens/s that keeps listing facts is a
    # half-hour call; a structured output cut short fails to parse and the
    # step records it, which is the better outcome.
    ollama_num_predict: int = 3072
    ollama_num_predict_fast: int = 1536
    ollama_reasoning: bool = False
    ollama_temperature: float = 0.2
    # Keep the weights loaded between calls; reloading 5 GB per request is
    # the difference between seconds and a minute.
    ollama_keep_alive: str = "30m"

    # When set, every request except /health must carry it in X-Proxy-Secret.
    # Set in deployments where the API sits behind a trusted proxy (see
    # app.proxy_auth); leave empty for local development.
    proxy_secret: str = ""

    # Small-to-big: child_chunk_size_tokens is the unit that gets embedded and
    # matched, and that a citation quotes. parent_window_radius neighbours either
    # side form the window the model actually reads, so the effective context per
    # citation is roughly child * (2 * radius + 1).
    # Must stay below child_chunk_size_tokens - the splitter refuses an overlap
    # larger than the chunk it's overlapping. Validated below rather than left to
    # be discovered on the first ingest.
    chunk_overlap_tokens: int = 50
    child_chunk_size_tokens: int = 200
    parent_window_radius: int = 1

    # Hybrid retrieval: alpha blends Weaviate's native BM25 + vector search
    # (0 = pure keyword, 1 = pure vector). retrieval_candidates is the pool
    # size fetched before reranking narrows it down.
    retrieval_candidates: int = 60
    hybrid_alpha: float = 0.5
    # The agentic layer: an LLM call that routes the question to collections,
    # splits it into sub-queries and infers filters before retrieval. Off means
    # one unfiltered query per collection - the baseline the benchmark compares
    # against, and a way to keep serving if the planner's provider is down.
    planner_enabled: bool = True
    # The planner may split a question into this many collection-specific
    # sub-queries. Each gets its own candidate pool; the union is reranked
    # against the original question.
    planner_max_subqueries: int = 4
    # A sub-query whose filters return fewer candidates than this is re-run
    # unfiltered: a planner that over-narrows must not turn into an empty answer.
    min_candidates_per_subquery: int = 5
    # How many reranked passages search mode returns for review.
    search_results: int = 10
    # Research mode: passes of retrieval (the plan, then a review's follow-ups),
    # follow-up searches a review may ask for, and passages the memo is
    # written from.
    research_max_rounds: int = 2
    research_max_follow_ups: int = 3
    research_results: int = 12
    research_concurrency: int = 2
    # Citation-graph expansion, bounded so the reranker's pool stays sane:
    # passages pulled in per authority the question names, and documents
    # one hop from the top candidates when the question is relational.
    graph_expansion_enabled: bool = True
    graph_max_lookup_passages: int = 12
    graph_max_neighbours: int = 8
    # The cross-encoder costs ~70 ms per candidate on a CPU, so expansion may
    # not grow the pool past this: its passages displace the weakest hybrid
    # candidates instead, and the request path's cost stays flat.
    graph_candidate_budget: int = 40
    # Topic-tree expansion (RAPTOR): summary nodes consulted per query, leaf
    # passages taken per node. Off until a tree has been built.
    topics_enabled: bool = False
    topics_max_nodes: int = 3
    topics_max_leaves: int = 6
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
    # "local" runs a sentence-transformers cross-encoder in-process; "cohere"
    # calls the hosted reranker. Local by default: it removes a per-query
    # network call and a provider quota that can halt the pipeline outright.
    reranker_provider: Literal["local", "cohere"] = "local"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_model: str = "rerank-v3.5"
    # Optional third stage: duoT5 pairwise refinement over the finalists.
    # Off by default because it is quadratic - k candidates cost k*(k-1)
    # forward passes - so it is only ever worth running on a short list the
    # cross-encoder has already narrowed.
    pairwise_rerank_enabled: bool = False
    pairwise_model: str = "castorini/duot5-base-msmarco"
    pairwise_max_candidates: int = 5
    rerank_top_n: int = 5
    rerank_relevance_threshold: float = 0.35
    # Score the document's title with each passage: a child chunk seldom names
    # the Act or the file it comes from, and the question usually does.
    rerank_with_title: bool = True

    # Anonymous access has no auth, so this bounds abuse per client instead.
    rate_limit_query: str = "30/minute"
    rate_limit_upload: str = "20/minute"
    rate_limit_research: str = "6/minute"

    # Matters: the user's own documents. Stored under data/matters, one
    # directory per matter; indexed in the background, at most this many at
    # once (the embedder is a CPU model).
    max_upload_size_mb: int = 25
    ingest_concurrency: int = 2

    # Corpus ingestion: objects per Weaviate batch insert.
    ingest_batch_size: int = 200

    # Resilience for outbound provider calls. Bounded on purpose: an unbounded
    # retry against a rate-limited provider turns one slow request into a stalled
    # worker, which is how the ingestion hangs in this project started.
    external_timeout_seconds: float = 60.0
    external_max_retries: int = 3
    circuit_breaker_failures: int = 5
    circuit_breaker_reset_seconds: float = 30.0

    # Caches. Embeddings are content-addressed on disk; retrieval and plans are
    # short-lived; the LLM cache is process-local.
    embedding_cache_enabled: bool = True
    retrieval_cache_ttl_seconds: float = 300.0
    llm_cache_enabled: bool = True
    # How often the catalog is rebuilt from the database, so an ingest in another
    # process shows up without a restart.
    catalog_refresh_seconds: float = 600.0

    # Langfuse tracing. Absent keys disable tracing entirely rather than erroring,
    # so local runs and CI never need a Langfuse project.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        """Reject chunk settings that can't produce chunks.

        Caught here so a bad combination fails at startup, in every environment,
        rather than surfacing as an ingestion error later. This exact mismatch
        shipped once because a local .env override masked an incompatible
        default - CI, which has no override, was the only place it showed up.
        """
        if self.chunk_overlap_tokens >= self.child_chunk_size_tokens:
            raise ValueError(
                f"chunk_overlap_tokens ({self.chunk_overlap_tokens}) must be smaller than "
                f"child_chunk_size_tokens ({self.child_chunk_size_tokens})"
            )
        if self.parent_window_radius < 0:
            raise ValueError("parent_window_radius cannot be negative")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
