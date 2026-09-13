from langchain_core.documents import Document
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from app.config import Settings

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
        chunk_size=settings.chunk_size_tokens,
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
    return chunks
