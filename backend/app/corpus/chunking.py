"""From a whole document to the children that get embedded and cited."""

from langchain_core.documents import Document

from app.config import Settings
from app.corpus.documents import SourceDocument
from app.corpus.normalize import normalize
from app.corpus.splitting import chunk_documents


def to_document(source: SourceDocument) -> Document:
    """A source document as the splitter sees it, provenance in metadata.

    Dates go in as ISO strings: metadata rides through the splitter and into the
    vector store's property map, and a `date` object survives neither cleanly.
    """
    metadata = {
        "collection": source.collection,
        "doc_id": source.doc_id,
        "url": source.url,
        "title": source.title,
        "year": source.year,
        "version_date": source.version_date.isoformat() if source.version_date else None,
    }
    if source.collection == "case_law":
        metadata.update(
            court_code=source.court_code,
            court=source.court,
            decision_date=source.decision_date.isoformat() if source.decision_date else None,
        )
    return Document(page_content=normalize(source.text), metadata=metadata)


def chunk_sources(sources: list[SourceDocument], settings: Settings) -> list[Document]:
    return chunk_documents([to_document(s) for s in sources], settings)
