"""Embeddings, either hosted (Cohere) or local (sentence-transformers).

Local is the default. The hosted model is good, but every ingest and every query
needs an embedding, so a provider quota is a hard dependency for the entire
pipeline - ingestion and retrieval both stop dead when it runs out. Running a
small model in-process removes that.

Vectors from different models are not interchangeable: they have different
dimensionality and different geometry. Switching providers means re-ingesting
every document, which is why `embedding_provider` is deliberately not something
to flip casually on a populated index.
"""

import logging

from langchain_core.embeddings import Embeddings

from app.caching import CachedEmbeddings
from app.config import Settings

logger = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}


class LocalEmbeddings(Embeddings):
    """sentence-transformers embeddings, loaded once per process.

    Queries and documents are embedded with the same model but, for models
    trained with asymmetric prefixes (the BGE family), the query side gets its
    instruction prefix. Without it a query embeds as though it were a passage
    and retrieval quality drops for no visible reason.
    """

    def __init__(self, model_name: str, query_prefix: str = ""):
        self._model_name = model_name
        self._query_prefix = query_prefix

    @property
    def _model(self):
        if self._model_name not in _model_cache:
            from sentence_transformers import SentenceTransformer

            logger.info("loading embedding model %s", self._model_name)
            _model_cache[self._model_name] = SentenceTransformer(self._model_name)
        return _model_cache[self._model_name]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            f"{self._query_prefix}{text}", normalize_embeddings=True, show_progress_bar=False
        )
        return vector.tolist()


def build_embeddings(settings: Settings) -> Embeddings:
    """The configured embedder, behind a content-addressed cache."""
    if settings.embedding_provider == "cohere":
        from langchain_cohere import CohereEmbeddings

        # max_retries/timeout set explicitly: the client's defaults leave a
        # request able to hang far longer than ingestion should tolerate, and an
        # unbounded retry against a rate-limited key just prolongs the stall.
        embeddings: Embeddings = CohereEmbeddings(
            model=settings.embedding_model,
            cohere_api_key=settings.cohere_api_key,
            max_retries=settings.external_max_retries,
            request_timeout=settings.external_timeout_seconds,
        )
        model_name = settings.embedding_model
    else:
        embeddings = LocalEmbeddings(
            settings.local_embedding_model, settings.local_embedding_query_prefix
        )
        model_name = settings.local_embedding_model

    if not settings.embedding_cache_enabled:
        return embeddings
    # Keyed by model name as well as text, so switching providers can't serve
    # vectors from the previous one.
    return CachedEmbeddings(embeddings, model=model_name)


def warm_embeddings(settings: Settings) -> None:
    """Load local weights at startup rather than inside the first request."""
    if settings.embedding_provider != "local":
        return
    LocalEmbeddings(settings.local_embedding_model).embed_query("warmup")
