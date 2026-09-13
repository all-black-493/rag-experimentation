from pydantic import BaseModel

from app.metadata import SourceType


class IngestUrlRequest(BaseModel):
    url: str


class IngestResponse(BaseModel):
    source: str
    chunks_indexed: int


class QueryRequest(BaseModel):
    question: str


class Citation(BaseModel):
    index: int
    source: str
    title: str
    source_type: SourceType
    page: int | None = None
    text: str
    doc_id: str | None = None
    bbox: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    favicon_url: str | None = None
    thumbnail_url: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
