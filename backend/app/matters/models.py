"""A matter and the documents in it - the API's shape and the store's record."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.analysis.models import CaseAnalysis

DocumentKind = Literal["pdf", "docx", "text"]
# queued/running: the ingest job hasn't finished. indexed: searchable.
DocumentStatus = Literal["queued", "running", "indexed", "failed"]


class DocumentProfile(BaseModel):
    """What one model call reads off a document once it is indexed.

    Enrichment, not evidence: it tells the planner what the document is so a
    question can be routed to it, and the reader what they uploaded. Nothing
    here is ever cited.
    """

    summary: str = Field(description="Two or three sentences on what the document is and says.")
    document_type: str = Field(
        description="Short label: contract, plaint, affidavit, judgment, demand letter, "
        "witness statement, correspondence, other."
    )
    parties: list[str] = Field(default_factory=list, description="Names of the parties, if any.")
    dates: list[str] = Field(
        default_factory=list,
        description="Dates the document turns on, ISO where possible, each with a few words "
        "on what it is.",
    )


class MatterDocument(BaseModel):
    doc_id: str
    name: str
    kind: DocumentKind
    bytes: int
    status: DocumentStatus = "queued"
    pages: int | None = None
    chunks: int | None = None
    error: str | None = None
    profile: DocumentProfile | None = None
    # Why the profile is missing, when it is: the document is still searchable.
    profile_error: str | None = None
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Matter(BaseModel):
    id: str
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    documents: list[MatterDocument] = Field(default_factory=list)
    # The last case analysis run over the documents, if one has been.
    analysis: CaseAnalysis | None = None

    def document(self, doc_id: str) -> MatterDocument | None:
        return next((d for d in self.documents if d.doc_id == doc_id), None)
