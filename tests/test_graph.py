from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.retrieval.graph import generate
from app.retrieval.state import GraphState


class FakeThinkingLLM:
    """Mimics a chat model with thinking enabled: content is a list of blocks,
    not a plain string, so .content alone would break a str-typed answer field."""

    def invoke(self, _message, config=None) -> AIMessage:
        return AIMessage(
            content=[
                {"type": "thinking", "thinking": "reasoning...", "signature": "abc"},
                {"type": "text", "text": "The limit is $150 per night [1]."},
            ]
        )


def test_generate_extracts_text_when_content_is_block_list():
    state: GraphState = {
        "question": "What is the hotel limit?",
        "documents": [Document(page_content="...", metadata={"source": "policy.md"})],
        "answer": "",
        "grounded": False,
    }

    result = generate(state, FakeThinkingLLM())

    assert result["answer"] == "The limit is $150 per night [1]."
