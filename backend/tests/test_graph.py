from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.retrieval.answer import generate
from app.retrieval.graph import route_after_rerank, route_after_verify
from app.retrieval.rerank import rerank


class FakeThinkingLLM:
    """Mimics a chat model with thinking enabled: content is a list of blocks,
    not a plain string, so .content alone would break a str-typed answer field."""

    def invoke(self, _message, config=None) -> AIMessage:
        return AIMessage(
            content=[
                {"type": "thinking", "thinking": "reasoning...", "signature": "abc"},
                {"type": "text", "text": "The penalty is a fine [1]."},
            ]
        )


def test_generate_extracts_text_when_content_is_block_list():
    state = {
        "question": "What is the penalty?",
        "mode": "ask",
        "documents": [Document("...", metadata={"collection": "legislation", "title": "Act"})],
        "answer": "",
        "grounded": False,
    }

    assert generate(state, FakeThinkingLLM())["answer"] == "The penalty is a fine [1]."


def test_search_mode_stops_after_reranking_even_with_results():
    assert route_after_rerank({"mode": "search", "documents": [Document("x")]}) == "search"
    assert route_after_rerank({"mode": "search", "documents": []}) == "search"


def test_ask_mode_answers_with_results_and_declines_without():
    assert route_after_rerank({"mode": "ask", "documents": [Document("x")]}) == "answer"
    assert route_after_rerank({"mode": "ask", "documents": []}) == "decline"


def test_ungrounded_answers_are_declined():
    assert route_after_verify({"grounded": True}) == "grounded"
    assert route_after_verify({"grounded": False}) == "ungrounded"


class ScoreAll:
    """Scores every candidate equally above threshold, in input order."""

    def compress_documents(self, documents, query):
        return [
            Document(d.page_content, metadata={**d.metadata, "relevance_score": 0.9})
            for d in documents
        ]


def test_rerank_keeps_more_passages_in_search_mode_than_in_ask_mode():
    documents = [Document(f"c{i}", metadata={"url": f"u{i}", "chunk_index": 0}) for i in range(8)]
    keep = {"ask": 3, "search": 6}

    ask = rerank({**_state(documents), "mode": "ask"}, ScoreAll(), relevance_threshold=0.5, keep=keep)
    search = rerank(
        {**_state(documents), "mode": "search"}, ScoreAll(), relevance_threshold=0.5, keep=keep
    )

    assert len(ask["documents"]) == 3
    assert len(search["documents"]) == 6


def _state(documents):
    return {"question": "q", "documents": documents, "answer": "", "grounded": False}


class FlakyVerifier:
    """Says 'not grounded' once, then 'grounded' - the one-bad-sample case."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _message, config=None):
        from app.retrieval.grounding import GroundednessCheck

        self.calls += 1
        return GroundednessCheck(grounded=self.verdicts.pop(0), reason="r")


def test_one_ungrounded_verdict_gets_a_second_opinion():
    from app.retrieval.answer import verify

    state = {"question": "q", "documents": [Document("p")], "answer": "a [1]", "grounded": False}
    flaky = FlakyVerifier([False, True])

    assert verify(state, flaky)["grounded"] is True
    assert flaky.calls == 2


def test_two_ungrounded_verdicts_withdraw_the_answer():
    from app.retrieval.answer import verify

    state = {"question": "q", "documents": [Document("p")], "answer": "a [1]", "grounded": False}
    flaky = FlakyVerifier([False, False])

    assert verify(state, flaky)["grounded"] is False
    assert flaky.calls == 2


def test_a_grounded_verdict_needs_no_second_call():
    from app.retrieval.answer import verify

    state = {"question": "q", "documents": [Document("p")], "answer": "a [1]", "grounded": False}
    once = FlakyVerifier([True])

    assert verify(state, once)["grounded"] is True
    assert once.calls == 1
