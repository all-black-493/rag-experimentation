from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.corpus.parenting import window


def build_splitter(settings: Settings) -> RecursiveCharacterTextSplitter:
    """A token-aware splitter targeting the configured child size and overlap.

    Uses tiktoken's cl100k_base encoding purely as a token-count proxy, independent
    of which model ultimately consumes the chunks. The default separators fall
    back from paragraph to line to sentence to word, so a child ends at a
    boundary a reader would recognise - unlike the corpus's original windows.
    """
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=settings.child_chunk_size_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
    )


def chunk_documents(documents: list[Document], settings: Settings) -> list[Document]:
    """Split documents into token-bounded children, each carrying its parent window.

    Children keep their document's metadata and gain `chunk_index` and
    `parent_text`. Windows are built per document so one never straddles two.
    """
    chunks = build_splitter(settings).split_documents(documents)

    by_url: dict[str, list[Document]] = {}
    for chunk in chunks:
        by_url.setdefault(chunk.metadata["url"], []).append(chunk)

    for group in by_url.values():
        texts = [c.page_content for c in group]
        for i, chunk in enumerate(group):
            chunk.metadata["chunk_index"] = i
            chunk.metadata["parent_text"] = window(texts, i, settings.parent_window_radius)
    return chunks
