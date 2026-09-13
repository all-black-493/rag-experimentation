from langchain_core.embeddings import Embeddings
from langchain_weaviate import WeaviateVectorStore
from weaviate.client import WeaviateClient

from app.config import Settings

# Metadata keys populated by app.ingestion.loaders/pdf, returned alongside chunk
# text so the retrieval graph can cite a chunk's origin - never inferred from
# LLM output. doc_id/bbox/page_width/page_height are PDF-only (page + highlight);
# favicon_url is web-only.
CITATION_ATTRIBUTES = [
    "source",
    "title",
    "source_type",
    "page",
    "doc_id",
    "bbox",
    "page_width",
    "page_height",
    "favicon_url",
    "thumbnail_url",
]


def build_vector_store(
    client: WeaviateClient, embeddings: Embeddings, settings: Settings
) -> WeaviateVectorStore:
    """Bind a WeaviateVectorStore to the given collection.

    The underlying Weaviate collection is created automatically on first write
    if it doesn't exist yet, with multi-tenancy enabled so each session's
    documents are physically isolated from every other session's.
    """
    return WeaviateVectorStore(
        client=client,
        index_name=settings.weaviate_collection,
        text_key="text",
        embedding=embeddings,
        attributes=CITATION_ATTRIBUTES,
        use_multi_tenancy=True,
    )


def tenant_exists(client: WeaviateClient, collection: str, tenant: str) -> bool:
    """Whether a tenant has ever written to the collection.

    Multi-tenant collections auto-create a tenant on first write, but querying a
    tenant that doesn't exist yet raises rather than returning an empty result -
    check first so a fresh session's first query just sees "no documents."
    """
    return client.collections.get(collection).tenants.exists(tenant)
