"""Cross-encoder reranking, either hosted (Cohere) or local (sentence-transformers).

Both implement `compress_documents(documents, query)` returning copies carrying a
`relevance_score`, because that is the contract the graph's rerank node already
depends on - including the detail that they are *copies*, which is why the node
matches reordered results back to candidates by content rather than identity.

Local is the default. A cross-encoder is a small model doing 60 short forward
passes; running it in-process removes a network round trip, a per-query cost, and
- the reason this exists - a provider quota that can stop the whole pipeline.
"""

import logging
from typing import Protocol

from langchain_core.documents import Document

from app.config import Settings

logger = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}


class Reranker(Protocol):
    def compress_documents(self, documents, query: str): ...


class CrossEncoderReranker:
    """Local cross-encoder scoring each (query, chunk) pair.

    The model is loaded once and reused: loading weights per request would cost
    far more than the inference itself.
    """

    def __init__(self, model_name: str, top_n: int):
        self._model_name = model_name
        self._top_n = top_n

    @property
    def _model(self):
        if self._model_name not in _model_cache:
            from sentence_transformers import CrossEncoder

            logger.info("loading cross-encoder %s", self._model_name)
            _model_cache[self._model_name] = CrossEncoder(self._model_name)
        return _model_cache[self._model_name]

    def compress_documents(self, documents: list[Document], query: str) -> list[Document]:
        if not documents:
            return []

        scores = self._model.predict([(query, doc.page_content) for doc in documents])

        ranked = sorted(zip(documents, scores, strict=True), key=lambda p: p[1], reverse=True)
        return [
            Document(
                doc.page_content,
                # Copied, not mutated: the caller still holds the originals and
                # compares against them.
                metadata={**doc.metadata, "relevance_score": float(score)},
            )
            for doc, score in ranked[: self._top_n]
        ]


def build_reranker(settings: Settings) -> Reranker:
    # Scores enough for the longer of the two modes' lists; the rerank node cuts
    # to the mode's own size after applying the threshold.
    top_n = max(settings.rerank_top_n, settings.search_results)
    if settings.reranker_provider == "cohere":
        from langchain_cohere import CohereRerank

        return CohereRerank(
            model=settings.rerank_model,
            cohere_api_key=settings.cohere_api_key,
            top_n=top_n,
        )

    return CrossEncoderReranker(settings.cross_encoder_model, top_n)


def warm_reranker(settings: Settings) -> None:
    """Load the local model at startup rather than inside the first query.

    Without this the first user after a deploy pays several seconds of weight
    loading, and it lands inside the request rather than anywhere visible.
    """
    if settings.reranker_provider != "local":
        return
    reranker = CrossEncoderReranker(settings.cross_encoder_model, settings.rerank_top_n)
    # A real pair, not an empty list: compress_documents short-circuits on empty
    # input and would return without ever loading the weights.
    reranker.compress_documents([Document("warmup")], "warmup")
