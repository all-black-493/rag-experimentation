from langchain_core.documents import Document
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from app.config import Settings
from app.ingestion.parenting import window

_MARKDOWN_SUFFIXES = (".md", ".markdown")


def build_splitter(settings: Settings, *, markdown: bool = False) -> RecursiveCharacterTextSplitter:
    """Build a token-aware splitter targeting the configured chunk size and overlap.

    Uses tiktoken's cl100k_base encoding purely as a token-count proxy, independent
    of which model ultimately consumes the chunks.
    """
    separators = RecursiveCharacterTextSplitter.get_separators_for_language(Language.MARKDOWN)
    kwargs = {"separators": separators} if markdown else {}
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=settings.child_chunk_size_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
        **kwargs,
    )


def chunk_documents(documents: list[Document], settings: Settings) -> list[Document]:
    """Split loaded documents into token-bounded chunks, chosen per source type."""
    markdown_docs = [d for d in documents if d.metadata.get("source", "").endswith(_MARKDOWN_SUFFIXES)]
    other_docs = [d for d in documents if d not in markdown_docs]

    chunks: list[Document] = []
    if markdown_docs:
        chunks.extend(build_splitter(settings, markdown=True).split_documents(markdown_docs))
    if other_docs:
        chunks.extend(build_splitter(settings).split_documents(other_docs))

    _attach_parents(chunks, settings.parent_window_radius)
    return chunks


def _attach_parents(chunks: list[Document], radius: int) -> None:
    """Give each child the window of neighbours around it, per source document.

    Grouped by source so a window never spans two documents - the neighbouring
    chunk of the last child of one file is the first child of the next, which
    has nothing to do with it.
    """
    by_source: dict[str, list[Document]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.metadata.get("source", ""), []).append(chunk)

    for group in by_source.values():
        texts = [c.page_content for c in group]
        for i, chunk in enumerate(group):
            chunk.metadata["parent_text"] = window(texts, i, radius)
