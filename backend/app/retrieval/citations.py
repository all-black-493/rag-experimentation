from datetime import date, datetime
from typing import TypedDict

from langchain_core.documents import Document

from app.metadata import Collection


class Citation(TypedDict):
    index: int
    collection: Collection
    doc_id: str
    title: str
    url: str
    # Judgments only.
    court: str | None
    court_code: str | None
    decision_date: str | None
    year: int | None
    chunk_index: int | None
    # Matter documents only: the PDF page and the box on it the passage sits in.
    matter_id: str | None
    page: int | None
    bbox: list[float] | None
    page_width: float | None
    page_height: float | None
    # The passage that matched, and the window it sits in.
    text: str
    parent_text: str
    relevance_score: float | None
    # Why the citation graph pulled this passage in, when it did:
    # "cites Kaingu Elias Kasono v Republic".
    via: str | None


def _iso(value: object) -> str | None:
    """Weaviate hands `date` properties back as datetimes; the API speaks ISO dates."""
    if isinstance(value, datetime | date):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value) if value else None


def label(document: Document) -> str:
    """How a passage is introduced to the model and to the reader.

    Judgments: "Republic v Chumba [2025] KEMC 94 — Magistrates' Courts, 2025-05-15".
    Acts: "Traffic Act". The Act's section number, when the passage carries one,
    is in the text itself. The user's own documents say so, with the page, so
    the model never mistakes a party's contract for the law.
    """
    metadata = document.metadata
    title = metadata.get("title") or metadata.get("url", "unknown")
    if metadata.get("collection") == "case_law":
        court = metadata.get("court")
        decided = _iso(metadata.get("decision_date"))
        detail = ", ".join(part for part in (court, decided) if part)
        return f"{title} — {detail}" if detail else title
    if metadata.get("collection") == "matter":
        page = metadata.get("page")
        return f"{title} — the user's own document" + (f", page {page}" if page else "")
    return title


def context_text(document: Document) -> str:
    """What the model reads for a passage: the parent window, not just the child.

    The child is what matched; the window is what makes it interpretable. Falls
    back to the child for a document without one.
    """
    return document.metadata.get("parent_text") or document.page_content


def format_context(documents: list[Document]) -> str:
    """Render retrieved passages as a numbered block for the generation prompt."""
    return "\n\n".join(
        f"[{i}] ({label(doc)})\n{context_text(doc)}" for i, doc in enumerate(documents, start=1)
    )


def build_citations(documents: list[Document]) -> list[Citation]:
    """The citation list matching the [n] markers used in format_context.

    Every field comes from the retrieved Document's metadata - set once at
    ingestion - never from the LLM's generated answer. The model only ever sees
    numbered passages and refers back to them by number; it has no path to
    invent or alter what a citation points to.
    """
    return [
        Citation(
            index=i,
            collection=doc.metadata.get("collection", "legislation"),
            doc_id=doc.metadata.get("doc_id", ""),
            title=doc.metadata.get("title") or doc.metadata.get("url", "unknown"),
            url=doc.metadata.get("url", ""),
            court=doc.metadata.get("court"),
            court_code=doc.metadata.get("court_code"),
            decision_date=_iso(doc.metadata.get("decision_date")),
            year=doc.metadata.get("year"),
            chunk_index=doc.metadata.get("chunk_index"),
            matter_id=doc.metadata.get("matter_id"),
            page=doc.metadata.get("page"),
            bbox=doc.metadata.get("bbox"),
            page_width=doc.metadata.get("page_width"),
            page_height=doc.metadata.get("page_height"),
            text=doc.page_content,
            parent_text=context_text(doc),
            relevance_score=doc.metadata.get("relevance_score"),
            via=doc.metadata.get("via"),
        )
        for i, doc in enumerate(documents, start=1)
    ]
