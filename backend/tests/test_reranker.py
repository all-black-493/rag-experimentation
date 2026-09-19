from unittest.mock import patch

from langchain_core.documents import Document

from app.config import Settings
from app.retrieval import reranker as reranker_module
from app.retrieval.reranker import CrossEncoderReranker, build_reranker


class FakeCrossEncoder:
    """Stands in for the real model so these tests need no weights."""

    def __init__(self, scores):
        self._scores = scores
        self.calls = []

    def predict(self, pairs):
        self.calls.append(pairs)
        return self._scores[: len(pairs)]


def _reranker(scores, top_n=3):
    encoder = FakeCrossEncoder(scores)
    reranker_module._model_cache["fake-model"] = encoder
    return CrossEncoderReranker("fake-model", top_n=top_n), encoder


def test_reorders_by_score_not_input_order():
    docs = [Document("first"), Document("second"), Document("third")]
    reranker, _ = _reranker([0.1, 0.9, 0.5])

    result = reranker.compress_documents(docs, "q")

    assert [d.page_content for d in result] == ["second", "third", "first"]


def test_attaches_relevance_score_the_graph_filters_on():
    reranker, _ = _reranker([0.42])

    result = reranker.compress_documents([Document("only")], "q")

    assert result[0].metadata["relevance_score"] == 0.42


def test_truncates_to_top_n():
    docs = [Document(str(i)) for i in range(5)]
    reranker, _ = _reranker([0.5, 0.4, 0.3, 0.2, 0.1], top_n=2)

    assert len(reranker.compress_documents(docs, "q")) == 2


def test_returns_copies_so_candidates_stay_untouched():
    """The graph matches reranked results back to candidates by content; it
    relies on the originals keeping their own metadata."""
    original = Document("text", metadata={"source": "a.pdf"})
    reranker, _ = _reranker([0.9])

    result = reranker.compress_documents([original], "q")

    assert result[0] is not original
    assert "relevance_score" not in original.metadata
    assert result[0].metadata["source"] == "a.pdf"


def test_scores_query_against_each_document():
    docs = [Document("alpha"), Document("beta")]
    reranker, encoder = _reranker([0.2, 0.8])

    reranker.compress_documents(docs, "the question")

    assert encoder.calls[0] == [("the question", "alpha"), ("the question", "beta")]


def test_empty_input_short_circuits_without_loading_a_model():
    """Called on a query whose retrieval found nothing; must not load weights."""
    assert CrossEncoderReranker("model-that-does-not-exist", top_n=3).compress_documents([], "q") == []


def test_provider_setting_selects_the_implementation():
    assert isinstance(
        build_reranker(Settings(reranker_provider="local")), CrossEncoderReranker
    )

    with patch("langchain_cohere.CohereRerank") as cohere:
        build_reranker(Settings(reranker_provider="cohere", cohere_api_key="x"))
        cohere.assert_called_once()


def test_leaders_are_collapsed_for_scoring_only():
    from app.retrieval.reranker import for_scoring

    text = "General damages....................Ksh. 120,000/= ______ total ---- ok"
    assert for_scoring(text) == "General damages...Ksh. 120,000/= ___ total --- ok"
    assert for_scoring("s. 26 of the Act... and more") == "s. 26 of the Act... and more"
