"""Index one document of a matter: parse, chunk, embed, insert, then profile.

Runs as a background job. The record in the store is the job's progress as
the reader sees it: `running` while this works, `indexed` once the chunks are
in, `failed` with the reason otherwise. A partial index is never left behind -
the document's chunks are cleared before they are written, so a retried job
writes them exactly once.
"""

import logging

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from weaviate.classes.data import DataObject
from weaviate.classes.query import Filter
from weaviate.classes.tenants import Tenant
from weaviate.client import WeaviateClient

from app.config import Settings
from app.matters.chunking import chunk_file
from app.matters.enrich import profile_document
from app.matters.pdf import page_count
from app.matters.store import MatterStore
from app.metadata import CLASS_NAMES, MATTER

logger = logging.getLogger(__name__)

# What the profile call reads: the first chunks, in order, up to this many.
_PROFILE_CHUNKS = 40


def _properties(chunk: Document) -> dict:
    return {
        "text": chunk.page_content,
        **{k: v for k, v in chunk.metadata.items() if k != "collection" and v is not None},
    }


def ensure_tenant(client: WeaviateClient, matter_id: str) -> None:
    """A matter's partition. Auto-creation covers inserts only; a delete or a
    query against a tenant that doesn't exist yet is an error, not an empty result."""
    collection = client.collections.use(CLASS_NAMES[MATTER])
    if not collection.tenants.exists(matter_id):
        collection.tenants.create([Tenant(name=matter_id)])


def index_document(
    client: WeaviateClient,
    embeddings: Embeddings,
    settings: Settings,
    matter_id: str,
    chunks: list[Document],
) -> None:
    """Replace a document's chunks in its matter's partition."""
    if not chunks:
        return
    ensure_tenant(client, matter_id)
    handle = client.collections.use(CLASS_NAMES[MATTER]).with_tenant(matter_id)
    doc_id = chunks[0].metadata["doc_id"]
    handle.data.delete_many(where=Filter.by_property("doc_id").equal(doc_id))
    vectors = embeddings.embed_documents([c.page_content for c in chunks])
    for start in range(0, len(chunks), settings.ingest_batch_size):
        batch = [
            DataObject(properties=_properties(chunk), vector=vector)
            for chunk, vector in zip(
                chunks[start : start + settings.ingest_batch_size],
                vectors[start : start + settings.ingest_batch_size],
                strict=True,
            )
        ]
        result = handle.data.insert_many(batch)
        if result.has_errors:
            first = next(iter(result.errors.values()))
            raise RuntimeError(f"insert failed: {first.message}")


def ingest(
    store: MatterStore,
    client: WeaviateClient,
    embeddings: Embeddings,
    settings: Settings,
    profiler: BaseChatModel | None,
    matter_id: str,
    doc_id: str,
) -> int:
    """The whole job for one document. Returns the number of chunks indexed."""
    matter = store.get(matter_id)
    document = matter.document(doc_id) if matter else None
    if document is None:
        raise KeyError(f"{doc_id} is not in matter {matter_id}")
    path = store.file_path(matter_id, doc_id)
    if path is None:
        raise FileNotFoundError(f"no stored file for {doc_id}")

    store.update_document(matter_id, doc_id, status="running", error=None)
    try:
        chunks = chunk_file(
            path, document.kind, settings, matter_id=matter_id, doc_id=doc_id, name=document.name
        )
        if not chunks:
            raise ValueError("no text could be extracted from the document")
        index_document(client, embeddings, settings, matter_id, chunks)
        pages = page_count(path) if document.kind == "pdf" else None
        store.update_document(matter_id, doc_id, status="indexed", chunks=len(chunks), pages=pages)
    except Exception as exc:
        store.update_document(matter_id, doc_id, status="failed", error=str(exc))
        raise

    # Enrichment after indexing: the document is searchable whether or not
    # the model is reachable.
    if profiler is not None:
        text = "\n\n".join(c.page_content for c in chunks[:_PROFILE_CHUNKS])
        try:
            profile = profile_document(profiler, document.name, text)
            store.update_document(matter_id, doc_id, profile=profile, profile_error=None)
        except Exception as exc:  # noqa: BLE001 - any provider failure is recorded, not raised
            logger.warning("profile failed for %s in %s: %s", document.name, matter_id, exc)
            store.update_document(matter_id, doc_id, profile_error=str(exc))
    return len(chunks)
