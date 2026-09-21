"""Research mode: the review between passes, the second pass, the memo, and the run."""

import asyncio

from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk

from app.jobs import JobRegistry
from app.retrieval import retrieve as retrieve_module
from app.retrieval.answer import generate
from app.retrieval.filters import LegalFilters
from app.retrieval.graph import route_after_rerank, route_after_review
from app.retrieval.plan import QueryPlan, SubQuery
from app.retrieval.retrieve import retrieve
from app.retrieval.review import Review, review
from app.retrieval.run import stream_query
from app.workflows import research
from app.workflows.runs import WorkflowRuns


def passage(i: int, collection="legislation") -> Document:
    return Document(
        f"passage {i}",
        metadata={
            "collection": collection,
            "title": "Employment Act",
            "url": f"https://x.test/{collection}",
            "chunk_index": i,
            "parent_text": f"around {i}",
        },
    )


def state(**overrides) -> dict:
    base = {
        "question": "Is a probationary employee entitled to notice on termination?",
        "mode": "research",
        "user_filters": LegalFilters(),
        "plan": QueryPlan(
            sub_queries=[SubQuery(query="probation notice", collection="legislation")],
            rationale="r",
        ),
        "retrieval": [
            {
                "query": "probation notice",
                "collection": "legislation",
                "filters": {},
                "retrieved": 2,
                "relaxed": False,
                "round": 1,
            }
        ],
        "documents": [passage(0), passage(1)],
        "answer": "",
        "grounded": None,
    }
    return {**base, **overrides}


class Reviewer:
    """A model that finds two gaps, repeats one search, and strays out of scope."""

    def __init__(self, review: Review | None = None, fail: bool = False):
        self.review = review
        self.fail = fail
        self.calls = 0

    def with_structured_output(self, schema):
        return self

    def invoke(self, message, config=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return self.review


FOUND = Review(
    missing="Only the Act was found; how courts have treated probationary notice is missing.",
    follow_ups=[
        {
            "query": "probationary employee termination notice",
            "collection": "case_law",
            "reason": "how courts applied s.42",
        },
        {"query": "probation notice", "collection": "legislation", "reason": "already run"},
        {
            "query": "contrary authority probation notice not required",
            "collection": "case_law",
            "reason": "the other side",
        },
        {
            "query": "my contract probation clause",
            "collection": "matter",
            "reason": "no matter in scope",
        },
    ],
)


def test_review_asks_for_admissible_follow_ups_only():
    reviewer = Reviewer(FOUND)
    result = review(state(), reviewer, max_follow_ups=3, max_rounds=2)

    assert result["rounds"] == 1
    assert [f.query for f in result["follow_ups"]] == [
        "probationary employee termination notice",
        "contrary authority probation notice not required",
    ]
    assert result["reviews"][0]["missing"].startswith("Only the Act")
    assert route_after_review({**state(), **result}) == "again"


def test_review_never_calls_the_model_once_rounds_are_spent():
    reviewer = Reviewer(FOUND)
    result = review(state(rounds=1), reviewer, max_follow_ups=3, max_rounds=2)
    assert reviewer.calls == 0
    assert result == {"rounds": 2, "follow_ups": []}
    assert route_after_review({**state(), **result}) == "answer"


def test_a_failed_review_costs_the_round_not_the_memo():
    result = review(state(), Reviewer(fail=True), max_follow_ups=3, max_rounds=2)
    assert result["follow_ups"] == []
    assert route_after_review({**state(), **result}) == "answer"


def test_research_routes_to_review_after_reranking():
    assert route_after_rerank({"mode": "research", "documents": [passage(0)]}) == "review"
    assert route_after_rerank({"mode": "research", "documents": []}) == "review"
    assert route_after_review({"mode": "research", "documents": [], "follow_ups": []}) == "decline"


class FakeSearch:
    def __init__(self):
        self.calls = []

    def __call__(
        self, client, collection, query, vector, *, alpha, fusion, limit, filters=None, tenant=None
    ):
        self.calls.append((collection, query))
        return [passage(10, collection), passage(0, collection)]


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.0]


def test_a_follow_up_pass_adds_to_the_pool_and_numbers_its_round(monkeypatch):
    search = FakeSearch()
    monkeypatch.setattr(retrieve_module, "hybrid_search", search)
    follow_ups = [SubQuery(query="probationary employee termination notice", collection="case_law")]

    result = retrieve(
        state(rounds=1, follow_ups=follow_ups),
        client=object(),
        embeddings=FakeEmbeddings(),
        k=20,
        alpha=0.5,
        fusion=None,
        min_candidates=5,
    )

    # Only the follow-up ran - not the plan, not the original question again.
    assert search.calls == [("case_law", "probationary employee termination notice")]
    # What the first pass kept comes first; the new candidates follow, de-duplicated.
    assert [d.metadata["url"] for d in result["documents"]] == [
        "https://x.test/legislation",
        "https://x.test/legislation",
        "https://x.test/case_law",
        "https://x.test/case_law",
    ]
    assert [r["round"] for r in result["retrieval"]] == [1, 2]
    assert result["follow_ups"] == []


class MemoWriter:
    def invoke(self, message, config=None):
        from langchain_core.messages import AIMessage

        text = message.to_string() if hasattr(message, "to_string") else str(message)
        assert "Issue, Law, Authorities, Analysis, Conclusion" in text
        return AIMessage(content="## Issue\nNotice on probation [1].")


def test_research_generates_from_the_memo_prompt():
    assert generate(state(), MemoWriter())["answer"].startswith("## Issue")


class ResearchGraph:
    """What LangGraph emits for a two-pass research run."""

    def stream(self, initial, config=None, stream_mode=None):
        plan = initial_plan = QueryPlan(
            sub_queries=[SubQuery(query="probation notice", collection="legislation")],
            rationale="r",
        )
        yield ("updates", {"plan": {"plan": plan}})
        yield ("updates", {"retrieve": {"documents": [passage(0), passage(1)], "retrieval": []}})
        yield ("updates", {"rerank": {"documents": [passage(0)]}})
        yield (
            "updates",
            {
                "review": {
                    "rounds": 1,
                    "follow_ups": [SubQuery(query="cases", collection="case_law")],
                    "reviews": [
                        {
                            "round": 1,
                            "missing": "cases",
                            "follow_ups": [
                                {"query": "cases", "collection": "case_law", "reason": "r"}
                            ],
                        }
                    ],
                }
            },
        )
        yield (
            "updates",
            {
                "retrieve": {
                    "documents": [passage(0), passage(5, "case_law")],
                    "retrieval": [],
                    "follow_ups": [],
                }
            },
        )
        yield ("updates", {"rerank": {"documents": [passage(0), passage(5, "case_law")]}})
        yield ("updates", {"review": {"rounds": 2, "follow_ups": []}})
        yield ("messages", (AIMessageChunk(content="## Issue"), {"langgraph_node": "generate"}))
        yield ("updates", {"generate": {"answer": "## Issue\nNotice [1] and [2]."}})
        yield ("updates", {"verify": {"grounded": True}})
        del initial_plan


def test_stream_reports_each_review_and_the_second_pass():
    events = list(stream_query(ResearchGraph(), "q", "research", LegalFilters()))
    kinds = [e.event for e in events]
    assert kinds == ["plan", "sources", "review", "sources", "review", "token", "done", "verdict"]
    first, second = (e.data for e in events if e.event == "review")
    assert first == {
        "round": 1,
        "missing": "cases",
        "follow_ups": [{"query": "cases", "collection": "case_law", "reason": "r"}],
        "another_pass": True,
    }
    assert second["another_pass"] is False and second["missing"] is None
    done = next(e for e in events if e.event == "done").data
    assert len(done.citations) == 2 and done.reviews[0]["round"] == 1


async def _run_workflow():
    runs = WorkflowRuns(JobRegistry(max_concurrency=1))
    run = runs.start(
        research.NAME,
        "q",
        lambda r: research.run(r, graph=ResearchGraph(), question="q", filters=LegalFilters()),
    )
    followed = [item["event"] async for item in run.follow()]
    # A late follower gets the same, replayed.
    replayed = [item["event"] async for item in run.follow()]
    for task in list(runs._jobs._tasks):
        await task
    return run, followed, replayed


def test_a_research_run_can_be_followed_live_and_replayed():
    run, followed, replayed = asyncio.run(_run_workflow())
    assert followed == [
        "plan",
        "sources",
        "review",
        "sources",
        "review",
        "token",
        "done",
        "verdict",
    ]
    assert replayed == followed
    assert run.done and run.job.status == "succeeded"
    done = next(item for item in run.events if item["event"] == "done")
    assert done["data"]["mode"] == "research" and len(done["data"]["citations"]) == 2
    assert run.summary()["events"] == 8


class FailingGraph:
    def stream(self, initial, config=None, stream_mode=None):
        yield ("updates", {"plan": {"plan": None}})
        raise RuntimeError("credit balance is too low")


async def _run_failing():
    runs = WorkflowRuns(JobRegistry(max_concurrency=1))
    run = runs.start(
        research.NAME,
        "q",
        lambda r: research.run(r, graph=FailingGraph(), question="q", filters=LegalFilters()),
    )
    followed = [item async for item in run.follow()]
    for task in list(runs._jobs._tasks):
        await task
    return run, followed


def test_a_failed_run_reports_the_error_to_followers_and_on_the_job():
    run, followed = asyncio.run(_run_failing())
    assert [item["event"] for item in followed] == ["plan", "error"]
    assert "credit balance" in followed[-1]["data"]["detail"]
    assert run.job.status == "failed" and "credit balance" in run.job.error


def test_workflow_routes_start_follow_and_report(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes import workflows
    from app.matters.store import MatterStore

    app = FastAPI()
    app.include_router(workflows.router)
    app.state.graph = ResearchGraph()
    app.state.matters = MatterStore(tmp_path)
    app.state.limiter = workflows.limiter

    with TestClient(app) as client:
        app.state.workflows = WorkflowRuns(JobRegistry(max_concurrency=1))
        accepted = client.post("/workflows/research", json={"question": "q"})
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]

        with client.stream("GET", f"/workflows/{job_id}/events") as response:
            body = "".join(response.iter_text())
        events = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event:")]
        assert events == [
            "plan",
            "sources",
            "review",
            "sources",
            "review",
            "token",
            "done",
            "verdict",
        ]

        status = client.get(f"/workflows/{job_id}").json()
        assert status["done"] and status["events"] == 8 and status["status"] == "succeeded"
        assert client.get("/workflows/nope").status_code == 404
        assert (
            client.post(
                "/workflows/research", json={"question": "q", "matter_id": "0" * 12}
            ).status_code
            == 404
        )


def test_provider_errors_are_told_in_their_own_words():
    from app.retrieval.run import failure_detail

    class ProviderError(Exception):
        @property
        def body(self):
            return {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your credit balance is too low.",
                },
            }

    assert failure_detail(ProviderError("Error code: 400 - {...}")) == (
        "The model provider refused the request: Your credit balance is too low."
    )
    assert failure_detail(RuntimeError("plain")) == "plain"
