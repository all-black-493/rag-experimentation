import asyncio

from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk

from app.api.streaming import sse_events
from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan, SubQuery
from app.retrieval.run import StreamEvent, run_query, stream_query


def passage(i: int) -> Document:
    return Document(
        f"passage {i}",
        metadata={
            "collection": "legislation",
            "title": "Traffic Act",
            "url": "https://x.test/act",
            "chunk_index": i,
            "parent_text": f"around passage {i}",
        },
    )


class FakeGraph:
    """Emits what LangGraph would for plan → retrieve → rerank → generate → verify."""

    def __init__(self, mode: str, answer: str = "A fine applies [1]. Also [7].", grounded=True):
        self.mode = mode
        self.answer = answer
        self.grounded = grounded
        self.plan = QueryPlan(
            sub_queries=[SubQuery(query="fine", collection="legislation")], rationale="r"
        )

    def _updates(self):
        yield ("updates", {"plan": {"plan": self.plan}})
        yield ("updates", {"retrieve": {"documents": [passage(0), passage(1)], "retrieval": []}})
        yield ("updates", {"rerank": {"documents": [passage(0)]}})
        if self.mode == "ask":
            for token in ("A fine ", "applies [1]. ", "Also [7]."):
                yield ("messages", (AIMessageChunk(content=token), {"langgraph_node": "generate"}))
            # The verifier's own model call must not leak into the answer stream.
            yield ("messages", (AIMessageChunk(content="{grounded}"), {"langgraph_node": "verify"}))
            yield ("updates", {"generate": {"answer": self.answer}})
            yield ("updates", {"verify": {"grounded": self.grounded}})

    def stream(self, state, config=None, stream_mode=None):
        yield from self._updates()

    def invoke(self, state, config=None):
        for kind, payload in self._updates():
            if kind == "updates":
                for update in payload.values():
                    state.update(update)
        return state


def test_ask_stream_emits_plan_sources_tokens_then_done():
    events = list(stream_query(FakeGraph("ask"), "q", "ask", LegalFilters()))

    assert [e.event for e in events] == ["plan", "sources", "token", "token", "token", "done"]
    assert events[0].data["plan"]["sub_queries"][0]["query"] == "fine"
    assert [c["index"] for c in events[1].data["citations"]] == [1]
    assert "".join(e.data["text"] for e in events if e.event == "token") == "A fine applies [1]. Also [7]."


def test_done_carries_the_enforced_answer_not_the_streamed_preview():
    """[7] points past the one citation; the final answer must not contain it."""
    done = list(stream_query(FakeGraph("ask"), "q", "ask", LegalFilters()))[-1].data

    assert done.answer == "A fine applies [1]. Also."
    assert done.grounded is True
    assert len(done.citations) == 1


def test_search_stream_has_no_tokens_and_no_answer():
    events = list(stream_query(FakeGraph("search"), "q", "search", LegalFilters()))

    assert [e.event for e in events] == ["plan", "sources", "done"]
    assert events[-1].data.answer is None
    assert len(events[-1].data.citations) == 1


def test_run_query_and_stream_query_agree():
    outcome = run_query(FakeGraph("ask"), "q", "ask", LegalFilters())
    streamed = list(stream_query(FakeGraph("ask"), "q", "ask", LegalFilters()))[-1].data

    assert outcome.answer == streamed.answer
    assert outcome.citations == streamed.citations


class ExplodingGraph(FakeGraph):
    def stream(self, state, config=None, stream_mode=None):
        yield ("updates", {"plan": {"plan": self.plan}})
        raise RuntimeError("weaviate down")


def test_a_failure_mid_stream_becomes_an_error_event():
    events = list(stream_query(ExplodingGraph("ask"), "q", "ask", LegalFilters()))

    assert [e.event for e in events] == ["plan", "error"]
    assert "weaviate down" in events[-1].data["detail"]


def test_sse_bridge_preserves_order_and_finalizes_done():
    def produce():
        yield StreamEvent("plan", {"a": 1})
        yield StreamEvent("token", {"text": "x"})
        yield StreamEvent("done", "outcome")

    async def collect():
        return [e async for e in sse_events(produce(), finalize=lambda o: {"final": o})]

    events = asyncio.run(collect())

    assert [e.event for e in events] == ["plan", "token", "done"]
    assert events[-1].data == {"final": "outcome"}
