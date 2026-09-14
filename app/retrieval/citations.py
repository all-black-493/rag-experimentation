from typing import TypedDict

from langchain_core.documents import Document

from app.metadata import SourceType


class Citation(TypedDict):
    index: int
    source: str
    title: str
    source_type: SourceType
    page: int | None
    text: str
    doc_id: str | None
    bbox: list[float] | None
    page_width: float | None
    page_height: float | None
    favicon_url: str | None
    thumbnail_url: str | None


def _label(document: Document) -> str:
    title = document.metadata.get("title") or document.metadata.get("source", "unknown")
    page = document.metadata.get("page")
    return f"{title}, p.{page}" if page is not None else title


def context_text(doc: Document) -> str:
    """What the model should read for this chunk.

    The parent window when small-to-big produced one, else the chunk itself.
    page_content stays the child so the citation's bbox keeps pointing at the
    lines that actually matched.
    """
    return doc.metadata.get("parent_text") or doc.page_content


def format_context(documents: list[Document]) -> str:
    """Render retrieved chunks as a numbered context block for the generation prompt."""
    return "\n\n".join(
        f"[{i}] ({_label(doc)})\n{context_text(doc)}" for i, doc in enumerate(documents, start=1)
    )


def build_citations(documents: list[Document]) -> list[Citation]:
    """Build the citation list matching the [n] markers used in format_context.

    Every field here comes from the retrieved Document's metadata - set once by
    app.ingestion at load time - never from the LLM's generated answer text. The
    model only ever sees `format_context`'s numbered passages and refers back to
    them by number; it has no path to invent or alter what a citation points to.

    `doc_id`/`bbox`/`page_width`/`page_height` are PDF-only (open the exact page,
    highlight the quoted region); `favicon_url` is web-only.
    """
    return [
        Citation(
            index=i,
            source=doc.metadata.get("source", "unknown"),
            title=doc.metadata.get("title", doc.metadata.get("source", "unknown")),
            source_type=doc.metadata.get("source_type", "text"),
            page=doc.metadata.get("page"),
            text=context_text(doc),
            # str(...): Weaviate's autoschema infers doc_id as its native `uuid`
            # type from the value's shape and returns a uuid.UUID, not a str.
            doc_id=str(doc.metadata["doc_id"]) if doc.metadata.get("doc_id") else None,
            bbox=doc.metadata.get("bbox"),
            page_width=doc.metadata.get("page_width"),
            page_height=doc.metadata.get("page_height"),
            favicon_url=doc.metadata.get("favicon_url"),
            thumbnail_url=doc.metadata.get("thumbnail_url"),
        )
        for i, doc in enumerate(documents, start=1)
    ]
