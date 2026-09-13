import uuid
from pathlib import Path

from langchain_weaviate import WeaviateVectorStore

from app.config import Settings
from app.ingestion.loaders import load_path, load_web
from app.ingestion.pdf import load_and_chunk_pdf, render_page_thumbnails
from app.ingestion.splitting import chunk_documents
from app.storage import save_page_thumbnail, save_pdf


def ingest_file(
    path: Path,
    vector_store: WeaviateVectorStore,
    settings: Settings,
    *,
    tenant: str,
    display_name: str | None = None,
) -> int:
    """Load, chunk, and index a local file. Returns the number of chunks written.

    `display_name` overrides the citation source/title, useful when `path` is a
    temporary file holding an uploaded document's original name. `tenant` scopes
    the write to one session's isolated partition of the collection.
    """
    name = display_name or path.name

    if path.suffix.lower() == ".pdf":
        doc_id = str(uuid.uuid4())
        save_pdf(tenant, doc_id, path.read_bytes())
        chunks = load_and_chunk_pdf(path, settings, doc_id=doc_id, display_name=name)
        cited_pages = {chunk.metadata["page"] for chunk in chunks}
        for page, thumbnail in render_page_thumbnails(path, cited_pages).items():
            save_page_thumbnail(tenant, doc_id, page, thumbnail)
    else:
        documents = load_path(path)
        for document in documents:
            document.metadata["source"] = name
            document.metadata["title"] = name
        chunks = chunk_documents(documents, settings)

    if chunks:
        vector_store.add_documents(chunks, tenant=tenant)
    return len(chunks)


def ingest_url(url: str, vector_store: WeaviateVectorStore, settings: Settings, *, tenant: str) -> int:
    """Fetch, chunk, and index a web page. Returns the number of chunks written."""
    documents = load_web(url)
    chunks = chunk_documents(documents, settings)
    if chunks:
        vector_store.add_documents(chunks, tenant=tenant)
    return len(chunks)
