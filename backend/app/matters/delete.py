"""Remove a document, or a whole matter, and everything derived from it.

Chunks first: those are what the model reads, so if a later step fails the
document is already unanswerable rather than half-gone and still cited.
"""

import logging

from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient

from app.matters.store import MatterStore
from app.metadata import CLASS_NAMES, MATTER

logger = logging.getLogger(__name__)


def delete_document(
    client: WeaviateClient, store: MatterStore, matter_id: str, doc_id: str
) -> bool:
    """False when the matter has no such document."""
    matter = store.get(matter_id)
    if matter is None or matter.document(doc_id) is None:
        return False
    collection = client.collections.use(CLASS_NAMES[MATTER])
    if collection.tenants.exists(matter_id):
        collection.with_tenant(matter_id).data.delete_many(
            where=Filter.by_property("doc_id").equal(doc_id)
        )
    store.remove_document(matter_id, doc_id)
    return True


def delete_matter(client: WeaviateClient, store: MatterStore, matter_id: str) -> bool:
    if store.get(matter_id) is None:
        return False
    collection = client.collections.use(CLASS_NAMES[MATTER])
    if collection.tenants.exists(matter_id):
        collection.tenants.remove([matter_id])
    store.delete(matter_id)
    return True
