import logging
from pathlib import Path

from langchain_weaviate import WeaviateVectorStore

from app.config import Settings
from app.ingestion.dedupe import already_ingested, content_id, record_ingestion
from app.ingestion.loaders import load_path, load_web
from app.ingestion.pdf import load_and_chunk_pdf, render_page_thumbnails
from app.ingestion.splitting import chunk_documents
from app.storage import UPLOADS_DIR, save_page_thumbnail, save_pdf

logger = logging.getLogger(__name__)


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
    content = path.read_bytes()
    doc_id = content_id(content)

    # Same bytes, same tenant: already indexed, so skip parsing, chunking and
    # embedding entirely. This is what makes a retried or duplicated upload cheap
    # and non-duplicating rather than a second full pass.
    previous = already_ingested(UPLOADS_DIR, tenant, doc_id)
    if previous is not None:
        logger.info("skipping %s - identical content already indexed as %s", name, doc_id)
        return previous["chunks"]

    if path.suffix.lower() == ".pdf":
        source_type = "pdf"
        save_pdf(tenant, doc_id, content)
        chunks = load_and_chunk_pdf(path, settings, doc_id=doc_id, display_name=name)
        cited_pages = {chunk.metadata["page"] for chunk in chunks}
        for page, thumbnail in render_page_thumbnails(path, cited_pages).items():
            save_page_thumbnail(tenant, doc_id, page, thumbnail)
    else:
        source_type = "text"
        documents = load_path(path)
        for document in documents:
            document.metadata["source"] = name
            document.metadata["title"] = name
            # Carried onto every chunk so the document can be deleted precisely
            # later; two uploads can share a display name, but not an id.
            document.metadata["doc_id"] = doc_id
        chunks = chunk_documents(documents, settings)

    if chunks:
        vector_store.add_documents(chunks, tenant=tenant)
    # Recorded only after a successful index, so a failed run is retried in full
    # rather than remembered as done.
    record_ingestion(
        UPLOADS_DIR, tenant, doc_id, source=name, source_type=source_type, chunks=len(chunks)
    )
    return len(chunks)


def ingest_url(url: str, vector_store: WeaviateVectorStore, settings: Settings, *, tenant: str) -> int:
    """Fetch, chunk, and index a web page. Returns the number of chunks written.

    Keyed on the URL rather than on the fetched bytes, unlike a file: a page that
    changed between two fetches is still the same source to the reader, and adding
    a link twice should be a no-op rather than a second copy of the page. Removing
    the source and adding it again is how to pick up a page that has changed.
    """
    doc_id = content_id(url.encode())

    previous = already_ingested(UPLOADS_DIR, tenant, doc_id)
    if previous is not None:
        logger.info("skipping %s - already indexed as %s", url, doc_id)
        return previous["chunks"]

    documents = load_web(url)
    for document in documents:
        document.metadata["doc_id"] = doc_id
    chunks = chunk_documents(documents, settings)

    if chunks:
        vector_store.add_documents(chunks, tenant=tenant)
    record_ingestion(
        UPLOADS_DIR, tenant, doc_id, source=url, source_type="web", chunks=len(chunks)
    )
    return len(chunks)
