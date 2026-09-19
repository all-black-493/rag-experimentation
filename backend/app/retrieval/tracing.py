from langchain_core.documents import Document


def traceable(doc: Document) -> dict:
    """One chunk as it should read in a trace: full text plus its provenance."""
    metadata = doc.metadata
    return {
        "collection": metadata.get("collection"),
        "title": metadata.get("title"),
        "url": metadata.get("url"),
        "court": metadata.get("court"),
        "year": metadata.get("year"),
        "chunk_index": metadata.get("chunk_index"),
        "text": doc.page_content,
    }
