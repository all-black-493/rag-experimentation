"""One document of a matter, as the chunks the index holds."""

from pathlib import Path

from langchain_core.documents import Document

from app.config import Settings
from app.corpus.splitting import chunk_documents
from app.matters.loaders import load_docx, load_text
from app.matters.models import DocumentKind
from app.matters.pdf import chunk_pdf


def file_url(matter_id: str, doc_id: str) -> str:
    """Where the original is served from; what a citation opens."""
    return f"/matters/{matter_id}/files/{doc_id}"


def chunk_file(
    path: Path, kind: DocumentKind, settings: Settings, *, matter_id: str, doc_id: str, name: str
) -> list[Document]:
    """Chunks carrying everything a citation to this document needs.

    PDFs keep page and box; text formats go through the corpus splitter and
    get the same small-to-big windows the corpus has.
    """
    provenance = {
        "collection": "matter",
        "matter_id": matter_id,
        "doc_id": doc_id,
        "title": name,
        "url": file_url(matter_id, doc_id),
    }
    if kind == "pdf":
        chunks = chunk_pdf(path, settings)
    else:
        text = load_docx(path) if kind == "docx" else load_text(path)
        chunks = chunk_documents([Document(page_content=text, metadata=dict(provenance))], settings)
    for chunk in chunks:
        chunk.metadata.update(provenance)
    return chunks
