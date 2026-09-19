"""What the planner produces: a validated plan, and the rules that bound it.

Kept apart from the planner node so the graph state can name `QueryPlan`
without importing the node - LangGraph resolves state annotations at runtime,
and a forward reference to a module that imports the state back is a cycle.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.metadata import Collection
from app.retrieval.catalog import Catalog
from app.retrieval.filters import LegalFilters, collections_in_scope


class SubQuery(BaseModel):
    query: str = Field(
        description="What to search for, phrased in the corpus's own terms: name the Act, "
        "section, parties or legal concept explicitly."
    )
    collection: Collection = Field(description="Which collection this sub-query is for.")
    courts: list[str] = Field(
        default_factory=list,
        description="Court codes to restrict to. Only when the question names a court or "
        "level. case_law only.",
    )
    year_from: int | None = Field(
        default=None, description="Earliest year, inclusive. Only when the question names one."
    )
    year_to: int | None = Field(
        default=None, description="Latest year, inclusive. Only when the question names one."
    )

    @field_validator("query")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("sub-query text is empty")
        return value

    @model_validator(mode="after")
    def _courts_only_for_case_law(self) -> "SubQuery":
        if self.collection != "case_law":
            self.courts = []
        if self.year_from and self.year_to and self.year_from > self.year_to:
            self.year_from, self.year_to = self.year_to, self.year_from
        return self

    def filters(self) -> LegalFilters:
        return LegalFilters(
            collections=(self.collection,),
            courts=tuple(self.courts),
            year_from=self.year_from,
            year_to=self.year_to,
        )


class QueryPlan(BaseModel):
    sub_queries: list[SubQuery] = Field(min_length=1, max_length=4)
    rationale: str = Field(description="One sentence: why these sub-queries and collections.")
    # How the plan came to be, so a trace can tell a planned query from a
    # fallback. Set by code, not by the model.
    origin: Literal["planner", "fallback"] = "planner"


def fallback_plan(question: str, scope: tuple[Collection, ...]) -> QueryPlan:
    """One unfiltered sub-query per collection in scope.

    What the pipeline did before it had a planner. Used when the planner fails
    or produces nothing usable, so a planning outage costs precision, never an
    answer.
    """
    return QueryPlan(
        sub_queries=[SubQuery(query=question, collection=c) for c in scope],
        rationale="Planner unavailable; searching every collection in scope.",
        origin="fallback",
    )


def constrain(plan: QueryPlan, user: LegalFilters, catalog: Catalog, limit: int) -> QueryPlan:
    """Bound a plan by what the user allowed and what the corpus contains.

    Drops sub-queries aimed at collections the user excluded and court codes the
    catalog doesn't list, and caps the count. If nothing survives, falls back
    rather than returning an empty plan.
    """
    known_courts = catalog.court_codes()
    kept = []
    for sub in plan.sub_queries:
        if not user.allows(sub.collection):
            continue
        sub.courts = [c for c in sub.courts if c in known_courts]
        kept.append(sub)
    if not kept:
        return fallback_plan(plan.sub_queries[0].query, collections_in_scope(user))
    return plan.model_copy(update={"sub_queries": kept[:limit]})
