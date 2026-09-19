from typing import Literal

from pydantic import BaseModel, Field

from app.matters.models import (  # noqa: F401 - re-exported as the /matters responses
    DocumentProfile,
    Matter,
    MatterDocument,
)
from app.metadata import Collection
from app.retrieval.catalog import Catalog  # noqa: F401 - re-exported as the /catalog response
from app.retrieval.filters import LegalFilters

Mode = Literal["search", "ask", "research"]


class QueryFilters(BaseModel):
    """The user's own restrictions. Hard constraints the planner works within."""

    collections: list[Collection] = []
    courts: list[str] = []
    year_from: int | None = Field(default=None, ge=1800, le=2100)
    year_to: int | None = Field(default=None, ge=1800, le=2100)

    def to_filters(self, matter_id: str | None = None) -> LegalFilters:
        return LegalFilters(
            collections=tuple(self.collections),
            courts=tuple(self.courts),
            year_from=self.year_from,
            year_to=self.year_to,
            matter_id=matter_id,
        )


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # search: ranked passages for review. ask: a grounded answer on top of them.
    mode: Mode = "ask"
    filters: QueryFilters = QueryFilters()
    # The user's own documents to search alongside the corpus.
    matter_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")

    def to_filters(self) -> LegalFilters:
        return self.filters.to_filters(self.matter_id)


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
    round: int = 1


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
    # Matter documents only: where on the page the passage is.
    matter_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    text: str
    parent_text: str
    relevance_score: float | None = None
    via: str | None = None


class WorkflowAccepted(BaseModel):
    job_id: str
    workflow: str
    question: str


class WorkflowStatus(BaseModel):
    job_id: str
    workflow: str
    question: str
    status: Literal["queued", "running", "succeeded", "failed"]
    error: str | None = None
    # Events recorded so far; `done` once the run has ended.
    events: int
    done: bool
    created_at: float


class MatterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class DocumentAccepted(BaseModel):
    """An upload was accepted; the document's status is on the matter."""

    matter_id: str
    doc_id: str
    job_id: str


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


class FollowUp(BaseModel):
    query: str
    collection: Collection
    reason: str


class ReviewOutcome(BaseModel):
    """What a research pass's review found missing, and what it searched for next."""

    round: int
    missing: str
    follow_ups: list[FollowUp]


class QueryResponse(BaseModel):
    mode: Mode
    question: str
    plan: Plan | None = None
    retrieval: list[SubQueryOutcome] = []
    # What the citation graph added, if anything.
    expansion: dict | None = None
    # Research mode: one entry per review that asked for another pass.
    reviews: list[ReviewOutcome] = []
    citations: list[Citation]
    # Ask and research only.
    answer: str | None = None
    grounded: bool | None = None

    @classmethod
    def from_outcome(cls, outcome) -> "QueryResponse":
        return cls(
            mode=outcome.mode,
            question=outcome.question,
            plan=outcome.plan.model_dump() if outcome.plan else None,
            retrieval=outcome.retrieval,
            expansion=outcome.expansion,
            reviews=outcome.reviews,
            citations=outcome.citations,
            answer=outcome.answer,
            grounded=outcome.grounded,
        )
