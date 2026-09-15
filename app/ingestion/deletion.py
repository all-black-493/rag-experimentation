"""Removing a document and everything derived from it.

Deletion has to be complete to mean anything. Removing a file is the user saying
"the model should no longer be able to see this", so anything left behind is a
correctness failure rather than untidiness:

  chunks          - the vectors; still retrievable otherwise
  stored PDF      - still served by /files/{doc_id}
  page thumbnails - still served, and they leak the page's content
  manifest record  - would make a later re-upload a no-op, so the user could
                     never add the document back
  retrieval cache - would keep answering from the deleted chunks until its TTL

Ordered deliberately: chunks first, because those are what the model reads. If a
later step fails the document is already unanswerable, rather than half-deleted
and still being cited.
"""

import logging
from pathlib import Path

from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient

from app.ingestion.dedupe import already_ingested, forget_ingestion
from app.storage import DOC_ID_PATTERN, delete_document_files

logger = logging.getLogger(__name__)


def delete_document(
    client: WeaviateClient,
    collection: str,
    uploads_dir: Path,
    tenant: str,
    doc_id: str,
) -> bool:
    """Delete a document and everything derived from it. False if the tenant has no such document.

    Tenant-scoped at every step, so a session can only ever delete its own - the
    same boundary that governs reading.
    """
    if not DOC_ID_PATTERN.match(doc_id):
        return False
    if already_ingested(uploads_dir, tenant, doc_id) is None:
        return False

    # The collection is created on first write, so a tenant that has a manifest
    # entry always has a collection to delete from.
    handle = client.collections.get(collection).with_tenant(tenant)
    result = handle.data.delete_many(where=Filter.by_property("doc_id").equal(doc_id))

    files = delete_document_files(tenant, doc_id)
    forget_ingestion(uploads_dir, tenant, doc_id)

    logger.info(
        "deleted %s for tenant %s: %s chunks, %s files",
        doc_id,
        tenant,
        result.successful,
        files,
    )
    return True
