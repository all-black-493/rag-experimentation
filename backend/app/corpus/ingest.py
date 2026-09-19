"""Index the corpus.

    uv run python -m app.corpus.ingest ../corpus/all_chunks.json
    uv run python -m app.corpus.ingest ../corpus/all_chunks.json --only case_law --limit 50

Idempotent per document: a document already complete in its collection is
skipped, and one left half-indexed by an interrupted run is cleared and redone.
So a run that was cut off picks up where it left off, and running twice indexes
nothing twice. The id is the document's URL, which for Kenya Law includes the
point-in-time version, so an amended Act is a new document rather than a
silent overwrite of the old one.

Two runs on disjoint collections (--only) can safely proceed in parallel.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from weaviate.classes.data import DataObject
from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient

from app.config import Settings, get_settings
from app.corpus.chunking import chunk_sources
from app.corpus.documents import SourceDocument, reconstruct
from app.metadata import CLASS_NAMES, COLLECTIONS, Collection
from app.vectorstore.client import weaviate_client
from app.vectorstore.embeddings import build_embeddings
from app.vectorstore.schema import ensure_collections

logger = logging.getLogger(__name__)

_DATE_PROPERTIES = ("version_date", "decision_date")


def load_rows(path: Path) -> list[dict]:
    with path.open() as handle:
        return json.load(handle)


def _properties(chunk: Document) -> dict:
    """A chunk's Weaviate properties: text plus every non-empty metadata field.

    Dates arrive as ISO date strings and leave as RFC 3339 timestamps, which is
    what a Weaviate `date` property accepts. Empty values are omitted rather
    than written as null.
    """
    properties = {"text": chunk.page_content}
    for key, value in chunk.metadata.items():
        if key == "collection" or value is None or value == "":
            continue
        if key in _DATE_PROPERTIES:
            value = f"{value}T00:00:00Z"
        properties[key] = value
    return properties


def indexed_chunks(client: WeaviateClient, collection: Collection, doc_id: str) -> int:
    """How many of a document's chunks the collection already holds."""
    handle = client.collections.use(CLASS_NAMES[collection])
    response = handle.aggregate.over_all(
        filters=Filter.by_property("doc_id").equal(doc_id), total_count=True
    )
    return response.total_count or 0


def index_document(
    client: WeaviateClient,
    embeddings: Embeddings,
    settings: Settings,
    document: SourceDocument,
) -> int | None:
    """Chunk, embed and insert one document.

    Returns chunks written, or None when the document was already complete. A
    partial document - the trace of a run that was interrupted mid-insert - is
    deleted and written again rather than trusted.
    """
    chunks = chunk_sources([document], settings)
    if not chunks:
        return 0

    handle = client.collections.use(CLASS_NAMES[document.collection])
    present = indexed_chunks(client, document.collection, document.doc_id)
    if present == len(chunks):
        return None
    if present:
        logger.warning("%s has %d of %d chunks; re-indexing", document.url, present, len(chunks))
        handle.data.delete_many(where=Filter.by_property("doc_id").equal(document.doc_id))

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
            # Fail the document loudly rather than leave it half-indexed and
            # marked as present by the next run's idempotency check.
            first = next(iter(result.errors.values()))
            raise RuntimeError(f"insert failed for {document.url}: {first.message}")
    return len(chunks)


def run(
    rows: list[dict],
    client: WeaviateClient,
    embeddings: Embeddings,
    settings: Settings,
    *,
    only: Collection | None = None,
    limit: int | None = None,
) -> dict:
    documents = reconstruct(rows)
    if only:
        documents = [d for d in documents if d.collection == only]
    if limit:
        documents = documents[:limit]

    created = ensure_collections(client)
    if created:
        logger.info("created collections: %s", ", ".join(created))

    started = time.monotonic()
    summary = {"documents": 0, "skipped": 0, "chunks": 0, "fallback_joins": 0}
    for i, document in enumerate(documents, start=1):
        written = index_document(client, embeddings, settings, document)
        if written is None:
            summary["skipped"] += 1
            continue
        summary["chunks"] += written
        summary["documents"] += 1
        summary["fallback_joins"] += document.fallback_joins
        if i % 50 == 0 or i == len(documents):
            elapsed = time.monotonic() - started
            print(
                f"  {i}/{len(documents)} documents, {summary['chunks']} chunks, {elapsed:.0f}s",
                file=sys.stderr,
            )
    summary["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="all_chunks.json")
    parser.add_argument("--only", choices=COLLECTIONS, help="index one collection only")
    parser.add_argument("--limit", type=int, help="index at most this many documents")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    rows = load_rows(args.corpus)
    print(f"{len(rows)} rows loaded", file=sys.stderr)

    with weaviate_client(settings) as client:
        summary = run(
            rows, client, build_embeddings(settings), settings, only=args.only, limit=args.limit
        )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
