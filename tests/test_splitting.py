from langchain_core.documents import Document

from app.config import Settings
from app.ingestion.splitting import chunk_documents


def make_settings(**overrides) -> Settings:
    return Settings(chunk_size_tokens=50, chunk_overlap_tokens=10, **overrides)


def test_chunks_stay_near_configured_token_size():
    long_text = "The quick brown fox jumps over the lazy dog. " * 200
    document = Document(page_content=long_text, metadata={"source": "sample.txt"})

    chunks = chunk_documents([document], make_settings())

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata["source"] == "sample.txt"


def test_consecutive_chunks_overlap():
    long_text = "Sentence number {}. ".format
    text = "".join(long_text(i) for i in range(500))
    document = Document(page_content=text, metadata={"source": "sample.txt"})

    chunks = chunk_documents([document], make_settings())

    first_tail = chunks[0].page_content[-20:]
    assert first_tail in chunks[1].page_content or chunks[1].page_content.startswith(first_tail[:5])


def test_markdown_documents_split_on_headers():
    markdown = "# Title\n\n" + ("Body text here. " * 100) + "\n\n## Section\n\n" + (
        "More body text. " * 100
    )
    document = Document(page_content=markdown, metadata={"source": "notes.md"})

    chunks = chunk_documents([document], make_settings())

    assert len(chunks) > 1
    assert any(chunk.page_content.startswith("# Title") for chunk in chunks)
