from langchain_core.documents import Document

from app.config import Settings
from app.corpus.splitting import chunk_documents


def make_settings(**overrides) -> Settings:
    return Settings(child_chunk_size_tokens=50, chunk_overlap_tokens=10, **overrides)


def make_document(text: str, url: str = "https://x.test/a") -> Document:
    return Document(page_content=text, metadata={"url": url, "title": "A"})


def test_chunks_stay_near_configured_token_size():
    long_text = "The quick brown fox jumps over the lazy dog. " * 200

    chunks = chunk_documents([make_document(long_text)], make_settings())

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata["url"] == "https://x.test/a"
        assert chunk.metadata["title"] == "A"


def test_children_are_numbered_per_document():
    text = "".join(f"Sentence number {i}. " for i in range(500))

    chunks = chunk_documents([make_document(text, "u1"), make_document(text, "u2")], make_settings())

    for url in ("u1", "u2"):
        indices = [c.metadata["chunk_index"] for c in chunks if c.metadata["url"] == url]
        assert indices == list(range(len(indices)))


def test_parent_windows_never_cross_documents():
    text = "".join(f"Sentence number {i}. " for i in range(200))

    chunks = chunk_documents(
        [make_document(text, "u1"), make_document("Other document entirely.", "u2")],
        make_settings(parent_window_radius=1),
    )

    last_of_first = [c for c in chunks if c.metadata["url"] == "u1"][-1]
    assert "Other document" not in last_of_first.metadata["parent_text"]


def test_consecutive_chunks_overlap():
    text = "".join(f"Sentence number {i}. " for i in range(500))

    chunks = chunk_documents([make_document(text)], make_settings())

    first_tail = chunks[0].page_content[-20:]
    assert first_tail in chunks[1].page_content or chunks[1].page_content.startswith(first_tail[:5])
