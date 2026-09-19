import pytest
from pydantic import ValidationError

from app.retrieval.catalog import Catalog, CollectionInfo, CourtInfo
from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan, SubQuery, constrain, fallback_plan
from app.retrieval.planner import plan


def catalog() -> Catalog:
    return Catalog(
        collections=[
            CollectionInfo(
                key="legislation", label="Legislation", description="Acts", documents=10, passages=100
            ),
            CollectionInfo(
                key="case_law",
                label="Case law",
                description="Judgments",
                documents=5,
                passages=50,
                courts=[CourtInfo(code="kesc", name="Supreme Court", rank=1, documents=2)],
            ),
        ]
    )


def test_courts_are_dropped_for_legislation_sub_queries():
    sub = SubQuery(query="penalty for speeding", collection="legislation", courts=["kesc"])
    assert sub.courts == []


def test_inverted_year_range_is_swapped_not_rejected():
    sub = SubQuery(query="q", collection="case_law", year_from=2026, year_to=2024)
    assert (sub.year_from, sub.year_to) == (2024, 2026)


def test_empty_query_text_is_rejected():
    with pytest.raises(ValidationError):
        SubQuery(query="   ", collection="case_law")


def test_plan_needs_at_least_one_and_at_most_four_sub_queries():
    with pytest.raises(ValidationError):
        QueryPlan(sub_queries=[], rationale="r")
    with pytest.raises(ValidationError):
        QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")] * 5, rationale="r")


def test_constrain_drops_collections_the_user_excluded():
    produced = QueryPlan(
        sub_queries=[
            SubQuery(query="statute", collection="legislation"),
            SubQuery(query="cases", collection="case_law"),
        ],
        rationale="both",
    )

    kept = constrain(produced, LegalFilters(collections=("case_law",)), catalog(), limit=4)

    assert [s.collection for s in kept.sub_queries] == ["case_law"]
    assert kept.origin == "planner"


def test_constrain_drops_court_codes_the_corpus_does_not_have():
    produced = QueryPlan(
        sub_queries=[SubQuery(query="q", collection="case_law", courts=["kesc", "made-up"])],
        rationale="r",
    )

    kept = constrain(produced, LegalFilters(), catalog(), limit=4)

    assert kept.sub_queries[0].courts == ["kesc"]


def test_constrain_falls_back_when_nothing_survives():
    produced = QueryPlan(
        sub_queries=[SubQuery(query="statute only", collection="legislation")], rationale="r"
    )

    kept = constrain(produced, LegalFilters(collections=("case_law",)), catalog(), limit=4)

    assert kept.origin == "fallback"
    assert [s.collection for s in kept.sub_queries] == ["case_law"]
    assert kept.sub_queries[0].query == "statute only"


def test_constrain_caps_the_number_of_sub_queries():
    produced = QueryPlan(
        sub_queries=[SubQuery(query=f"q{i}", collection="case_law") for i in range(4)],
        rationale="r",
    )

    assert len(constrain(produced, LegalFilters(), catalog(), limit=2).sub_queries) == 2


def test_fallback_plan_searches_every_collection_in_scope_unfiltered():
    produced = fallback_plan("what is the penalty?", ("legislation", "case_law"))

    assert [s.collection for s in produced.sub_queries] == ["legislation", "case_law"]
    assert all(s.query == "what is the penalty?" and not s.courts for s in produced.sub_queries)


class FailingLLM:
    def with_structured_output(self, _schema):
        raise RuntimeError("provider down")


def test_plan_node_degrades_to_the_fallback_when_the_planner_fails():
    state = {"question": "q", "mode": "ask", "user_filters": LegalFilters(collections=("case_law",))}

    result = plan(state, FailingLLM(), catalog(), max_subqueries=4)

    assert result["plan"].origin == "fallback"
    assert [s.collection for s in result["plan"].sub_queries] == ["case_law"]


class StructuredLLM:
    def __init__(self, produced: QueryPlan):
        self._produced = produced

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _message, config=None):
        return self._produced


def test_plan_node_returns_the_constrained_plan():
    produced = QueryPlan(
        sub_queries=[SubQuery(query="q", collection="case_law", courts=["nope"])], rationale="r"
    )
    state = {"question": "q", "mode": "ask", "user_filters": LegalFilters()}

    result = plan(state, StructuredLLM(produced), catalog(), max_subqueries=4)

    assert result["plan"].origin == "planner"
    assert result["plan"].sub_queries[0].courts == []
