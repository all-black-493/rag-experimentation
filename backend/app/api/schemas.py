from typing import Literal

from pydantic import BaseModel, Field

from app.metadata import Collection
from app.retrieval.catalog import Catalog  # noqa: F401 - re-exported as the /catalog response
from app.retrieval.filters import LegalFilters

Mode = Literal["search", "ask"]


class QueryFilters(BaseModel):
    """The user's own restrictions. Hard constraints the planner works within."""

    collections: list[Collection] = []
    courts: list[str] = []
    year_from: int | None = Field(default=None, ge=1800, le=2100)
    year_to: int | None = Field(default=None, ge=1800, le=2100)

    def to_filters(self) -> LegalFilters:
        return LegalFilters(
            collections=tuple(self.collections),
            courts=tuple(self.courts),
            year_from=self.year_from,
            year_to=self.year_to,
        )


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # search: ranked passages for review. ask: a grounded answer on top of them.
    mode: Mode = "ask"
    filters: QueryFilters = QueryFilters()


class SubQuery(BaseModel):
    query: str
    collection: Collection
    courts: list[str] = []
    year_from: int | None = None
    year_to: int | None = None


class Plan(BaseModel):
    sub_queries: list[SubQuery]
    rationale: str
    origin: Literal["planner", "fallback"]
    relationships: bool = False


class SubQueryOutcome(BaseModel):
    """How one sub-query fared - what the UI's plan strip is built from."""

    query: str
    collection: Collection
    filters: dict
    retrieved: int
    relaxed: bool


class Citation(BaseModel):
    index: int
    collection: Collection
    doc_id: str
    title: str
    url: str
    court: str | None = None
    court_code: str | None = None
    decision_date: str | None = None
    year: int | None = None
    chunk_index: int | None = None
    text: str
    parent_text: str
    relevance_score: float | None = None
    via: str | None = None


class GraphLink(BaseModel):
    """A document one citation away, with every way the link was written."""

    # Null when the corpus doesn't hold the cited authority.
    doc_id: str | None
    collection: Collection | None
    title: str | None
    url: str | None
    kind: Literal["cites", "applies"]
    parties: str | None = None
    # "section 204 of the Penal Code", "[2018] eKLR": as the citing passage wrote it.
    refs: list[str]
    # The first passage that made the link.
    via_doc_id: str
    via_chunk_index: int


class GraphNeighbourhood(BaseModel):
    doc_id: str
    cites: list[GraphLink]
    cited_by: list[GraphLink]


class QueryResponse(BaseModel):
    mode: Mode
    question: str
    plan: Plan | None = None
    retrieval: list[SubQueryOutcome] = []
    # What the citation graph added, if anything.
    expansion: dict | None = None
    citations: list[Citation]
    # Ask mode only.
    answer: str | None = None
    grounded: bool | None = None
