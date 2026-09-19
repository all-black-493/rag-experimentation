"""What a case analysis produces. Every item points at where it was read."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.retrieval.citations import Citation


class Party(BaseModel):
    name: str
    role: str = Field(description="Landlord, tenant, plaintiff, witness, advocate…")
    # 1-based index into `sources`; None when the party was named in no one passage.
    source: int | None = None


class Fact(BaseModel):
    statement: str
    source: int | None = None


class Event(BaseModel):
    """One dated thing that happened, in the document's own words."""

    # ISO date when the wording allowed one; sorting key.
    date: str | None = None
    # As written: "18th April 2025", "about April 2025".
    when: str
    description: str
    source: int | None = None


class Issue(BaseModel):
    question: str
    sources: list[int] = Field(default_factory=list)


class Authority(BaseModel):
    """An Act or a case the documents cite, resolved against the corpus where it can be."""

    ref: str
    kind: str  # case | statute
    key: str
    provision: str | None = None
    doc_id: str | None = None
    title: str | None = None
    url: str | None = None
    # Distinct corpus documents the citation graph shows applying or citing it.
    applied_by: int = 0
    sources: list[int] = Field(default_factory=list)


class Contradiction(BaseModel):
    point: str
    first: str
    second: str
    sources: list[int] = Field(default_factory=list)


class ResearchQuestion(BaseModel):
    question: str
    why: str


class CaseAnalysis(BaseModel):
    matter_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parties: list[Party] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    chronology: list[Event] = Field(default_factory=list)
    authorities: list[Authority] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    report: str | None = None
    # Steps that could not run, with why. The rest of the analysis stands.
    warnings: list[str] = Field(default_factory=list)
    # The passages the items point at, numbered like an answer's citations.
    sources: list[Citation] = Field(default_factory=list)
