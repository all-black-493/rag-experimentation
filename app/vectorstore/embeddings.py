from langchain_cohere import CohereEmbeddings
from langchain_core.embeddings import Embeddings

from app.caching import CachedEmbeddings
from app.config import Settings


def build_embeddings(settings: Settings) -> Embeddings:
    """Cohere embeddings behind a content-addressed cache.

    max_retries/timeout are set explicitly: the client's defaults leave a request
    able to hang far longer than the ingestion path should tolerate, and an
    unbounded retry against a rate-limited key just prolongs the stall.
    """
    embeddings = CohereEmbeddings(
        model=settings.embedding_model,
        cohere_api_key=settings.cohere_api_key,
        max_retries=settings.external_max_retries,
        request_timeout=settings.external_timeout_seconds,
    )
    if not settings.embedding_cache_enabled:
        return embeddings
    return CachedEmbeddings(embeddings, model=settings.embedding_model)
