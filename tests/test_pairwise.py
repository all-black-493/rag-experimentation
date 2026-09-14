from langchain_core.documents import Document

from app.retrieval.pairwise import PairwiseReranker


class StubPairwise(PairwiseReranker):
    """Preference driven by a fixed ranking, so no model weights are needed."""

    def __init__(self, better_first: list[str], max_candidates: int = 5):
        super().__init__("stub", max_candidates)
        self._rank = {text: i for i, text in enumerate(better_first)}

    def _preference(self, query: str, a: str, b: str) -> float:
        return 1.0 if self._rank[a] < self._rank[b] else 0.0


def _docs(*texts):
    return [Document(t) for t in texts]


def test_promotes_the_pairwise_winner():
    """The case pointwise scoring gets wrong: both look relevant, one is better."""
    reranker = StubPairwise(["domestic $150", "international $250", "filing deadline"])
    documents = _docs("international $250", "domestic $150", "filing deadline")

    result = reranker.rerank(documents, "domestic hotel rate")

    assert result[0].page_content == "domestic $150"


def test_records_the_score_it_ranked_on():
    reranker = StubPairwise(["a", "b"])

    result = reranker.rerank(_docs("b", "a"), "q")

    assert result[0].metadata["pairwise_score"] == 1.0
    assert result[1].metadata["pairwise_score"] == 0.0


def test_only_the_head_is_reordered():
    """Quadratic cost is bounded by reordering a cutoff, not the whole list."""
    reranker = StubPairwise(["c", "b", "a", "d", "e"], max_candidates=3)
    documents = _docs("a", "b", "c", "d", "e")

    result = [d.page_content for d in reranker.rerank(documents, "q")]

    assert result[:3] == ["c", "b", "a"]
    # The tail keeps its incoming order and is never scored.
    assert result[3:] == ["d", "e"]


def test_a_single_document_is_returned_untouched():
    """Nothing to compare against; must not invent a score or fail."""
    reranker = StubPairwise(["only"])
    documents = _docs("only")

    result = reranker.rerank(documents, "q")

    assert result[0].page_content == "only"
    assert "pairwise_score" not in result[0].metadata


def test_empty_input_is_safe():
    assert StubPairwise([]).rerank([], "q") == []


def test_original_documents_are_not_mutated():
    reranker = StubPairwise(["a", "b"])
    documents = _docs("a", "b")

    reranker.rerank(documents, "q")

    assert all("pairwise_score" not in d.metadata for d in documents)
