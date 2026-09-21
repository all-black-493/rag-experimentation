"""A matter's indexed passages, in reading order, grouped by document."""

from langchain_core.documents import Document
from weaviate.client import WeaviateClient

from app.metadata import CLASS_NAMES, MATTER
from app.vectorstore.schema import RETURN_PROPERTIES


def load_chunks(client: WeaviateClient, matter_id: str) -> dict[str, list[Document]]:
    """Every chunk of every indexed document, by doc_id, in chunk order."""
    collection = client.collections.use(CLASS_NAMES[MATTER])
    if not collection.tenants.exists(matter_id):
        return {}
    handle = collection.with_tenant(matter_id)
    by_document: dict[str, list[Document]] = {}
    for obj in handle.iterator(return_properties=RETURN_PROPERTIES[MATTER]):
        properties = dict(obj.properties)
        text = properties.pop("text")
        document = Document(page_content=text, metadata={**properties, "collection": MATTER})
        by_document.setdefault(properties["doc_id"], []).append(document)
    for chunks in by_document.values():
        chunks.sort(key=lambda d: d.metadata.get("chunk_index", 0))
    return by_document
