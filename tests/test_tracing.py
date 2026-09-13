from langchain_core.documents import Document

from app import tracing
from app.config import Settings
from app.retrieval.graph import rerank


class FakeReranker:
    """Returns copies in a new order, the way CohereRerank actually behaves."""

    def __init__(self, order: list[int], scores: list[float]):
        self._order = order
        self._scores = scores

    def compress_documents(self, documents, query):
        return [
            Document(
                documents[i].page_content,
                metadata={**documents[i].metadata, "relevance_score": score},
            )
            for i, score in zip(self._order, self._scores, strict=True)
        ]


def test_tracing_disabled_without_credentials():
    tracing.configure_tracing(Settings(langfuse_public_key="", langfuse_secret_key=""))

    assert tracing.tracing_enabled() is False
    assert tracing.build_callback_handler() is None


def test_observation_is_usable_when_tracing_is_off():
    """Nodes call .update() unconditionally, so the no-op has to accept it."""
    tracing.configure_tracing(Settings(langfuse_public_key="", langfuse_secret_key=""))

    with tracing.observation(as_type="retriever", name="retrieve") as span:
        span.update(output=[{"source": "a.pdf"}], metadata={"retrieved": 1})

    with tracing.trace(name="rag-query", session_id="tenant-1") as root:
        root.update(output={"answer": "..."})
        # Scored on every query, so a missing no-op here would 500 any
        # deployment running without Langfuse keys - CI included.
        root.score_trace(name="answered", value=True, data_type="BOOLEAN")
        root.score_trace(name="citation_coverage", value=0.5, data_type="NUMERIC")


def test_rerank_still_filters_and_orders_with_tracing_off():
    """The span wrapper must not change what the node returns."""
    tracing.configure_tracing(Settings(langfuse_public_key="", langfuse_secret_key=""))
    documents = [
        Document("chunk one", metadata={"source": "a.pdf", "doc_id": "1", "page": 1}),
        Document("chunk two", metadata={"source": "b.pdf", "doc_id": "2", "page": 2}),
        Document("chunk three", metadata={"source": "c.pdf", "doc_id": "3", "page": 3}),
    ]
    state = {"question": "q", "documents": documents, "answer": "", "grounded": False}

    # Reversed order; the last one falls below the threshold.
    result = rerank(state, FakeReranker([2, 1, 0], [0.9, 0.5, 0.05]), relevance_threshold=0.2)

    assert [doc.page_content for doc in result["documents"]] == ["chunk three", "chunk two"]
