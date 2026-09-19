from langchain_core.documents import Document
from weaviate.classes.query import HybridFusion

from app.retrieval import retrieve as retrieve_module
from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan, SubQuery
from app.retrieval.retrieve import retrieve


class FakeEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return [0.0]


def doc(url: str, index: int, collection: str = "case_law") -> Document:
    return Document(f"{url}#{index}", metadata={"url": url, "chunk_index": index, "collection": collection})


class FakeSearch:
    """Stands in for hybrid_search; records every call and answers from a table."""

    def __init__(self, answers: dict[tuple, list[Document]]):
        self.answers = answers
        self.calls: list[tuple] = []

    def __call__(
        self, client, collection, query, vector, *, alpha, fusion, limit, filters=None, tenant=None
    ):
        key = (collection, query, filters is not None)
        self.calls.append(key)
        self.tenants = {**getattr(self, "tenants", {}), collection: tenant}
        return self.answers.get(key, [])


def run(monkeypatch, plan: QueryPlan, search: FakeSearch, user=None, min_candidates=2):
    monkeypatch.setattr(retrieve_module, "hybrid_search", search)
    state = {"question": "q", "mode": "ask", "user_filters": user or LegalFilters(), "plan": plan}
    return retrieve(
        state,
        client=object(),
        embeddings=FakeEmbeddings(),
        k=10,
        alpha=0.5,
        fusion=HybridFusion.RELATIVE_SCORE,
        min_candidates=min_candidates,
    )


def test_results_from_every_sub_query_are_pooled_and_deduplicated(monkeypatch):
    shared = doc("u1", 0)
    search = FakeSearch(
        {
            ("legislation", "statute", False): [doc("act", 0, "legislation"), doc("act", 1, "legislation")],
            ("case_law", "cases", False): [shared, doc("u2", 0)],
            ("case_law", "more cases", False): [doc("u1", 0), doc("u3", 0)],
        }
    )
    plan = QueryPlan(
        sub_queries=[
            SubQuery(query="statute", collection="legislation"),
            SubQuery(query="cases", collection="case_law"),
            SubQuery(query="more cases", collection="case_law"),
        ],
        rationale="r",
    )

    result = run(monkeypatch, plan, search)

    urls = [(d.metadata["url"], d.metadata["chunk_index"]) for d in result["documents"]]
    assert urls == [("act", 0), ("act", 1), ("u1", 0), ("u2", 0), ("u3", 0)]
    # Three planned searches, then the original question once per collection.
    assert [r["retrieved"] for r in result["retrieval"]] == [2, 2, 2, 0, 0]


def test_a_planner_filter_that_returns_too_little_is_relaxed(monkeypatch):
    search = FakeSearch(
        {
            ("case_law", "q", True): [doc("u1", 0)],
            ("case_law", "q", False): [doc("u1", 0), doc("u2", 0), doc("u3", 0)],
        }
    )
    plan = QueryPlan(
        sub_queries=[SubQuery(query="q", collection="case_law", courts=["kesc"])], rationale="r"
    )

    result = run(monkeypatch, plan, search, min_candidates=2)

    assert len(result["documents"]) == 3
    assert result["retrieval"][0]["relaxed"] is True
    assert result["retrieval"][0]["filters"] == {}
    assert search.calls == [("case_law", "q", True), ("case_law", "q", False)]


def test_the_users_own_filter_is_never_relaxed(monkeypatch):
    search = FakeSearch({("case_law", "q", True): [doc("u1", 0)]})
    plan = QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")], rationale="r")

    result = run(monkeypatch, plan, search, user=LegalFilters(courts=("kesc",)), min_candidates=5)

    assert result["retrieval"][0]["relaxed"] is False
    assert result["retrieval"][0]["filters"] == {"courts": ["kesc"]}
    assert search.calls == [("case_law", "q", True)]


def test_enough_results_means_no_relaxation(monkeypatch):
    search = FakeSearch({("case_law", "q", True): [doc("u1", 0), doc("u2", 0)]})
    plan = QueryPlan(
        sub_queries=[SubQuery(query="q", collection="case_law", year_from=2025)], rationale="r"
    )

    result = run(monkeypatch, plan, search, min_candidates=2)

    assert result["retrieval"][0]["relaxed"] is False
    assert len(search.calls) == 1


def test_the_original_question_is_always_searched_in_every_planned_collection(monkeypatch):
    """A paraphrase can lose the words keyword search matches on; the plan only adds."""
    search = FakeSearch({})
    plan = QueryPlan(
        sub_queries=[
            SubQuery(query="rewritten statute query", collection="legislation"),
            SubQuery(query="rewritten case query", collection="case_law"),
        ],
        rationale="r",
    )

    run(monkeypatch, plan, search)

    assert search.calls == [
        ("legislation", "rewritten statute query", False),
        ("case_law", "rewritten case query", False),
        ("legislation", "q", False),
        ("case_law", "q", False),
    ]


def test_the_original_is_not_duplicated_when_the_plan_already_uses_it(monkeypatch):
    search = FakeSearch({})
    plan = QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")], rationale="r")

    run(monkeypatch, plan, search)

    assert search.calls == [("case_law", "q", False)]


def test_workers_inherit_the_request_context(monkeypatch):
    """Trace spans live in contextvars; a worker without the request's context would
    open its retriever span outside the request's trace."""
    import contextvars

    marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="unset")
    seen: list[str] = []

    class RecordingSearch(FakeSearch):
        def __call__(self, *args, **kwargs):
            seen.append(marker.get())
            return super().__call__(*args, **kwargs)

    marker.set("request")
    plan = QueryPlan(
        sub_queries=[SubQuery(query="a", collection="case_law"), SubQuery(query="b", collection="legislation")],
        rationale="r",
    )

    run(monkeypatch, plan, RecordingSearch({}))

    assert seen and all(value == "request" for value in seen)
