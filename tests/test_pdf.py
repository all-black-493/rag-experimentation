from pathlib import Path

import pymupdf

from app.config import Settings
from app.ingestion.pdf import chunk_pdf_blocks, extract_pdf_blocks, load_and_chunk_pdf


def make_pdf(path: Path, pages: list[list[str]]) -> None:
    """Write a PDF where each inner list is a page's paragraphs, stacked top to bottom."""
    doc = pymupdf.Document()
    for paragraphs in pages:
        page = doc.new_page()
        for i, text in enumerate(paragraphs):
            page.insert_text((72, 72 + i * 80), text)
    doc.save(str(path))


def test_extract_pdf_blocks_captures_page_and_bbox(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    make_pdf(pdf_path, pages=[["First paragraph."], ["Second page text."]])

    blocks = extract_pdf_blocks(pdf_path)

    assert [b["page"] for b in blocks] == [1, 2]
    assert "First paragraph" in blocks[0]["text"]
    assert all(len(b["bbox"]) == 4 for b in blocks)
    assert all(b["page_width"] > 0 and b["page_height"] > 0 for b in blocks)


def test_chunk_pdf_blocks_never_spans_pages(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    make_pdf(pdf_path, pages=[["Page one text."], ["Page two text."]])
    settings = Settings(chunk_size_tokens=650, chunk_overlap_tokens=100)

    chunks = chunk_pdf_blocks(extract_pdf_blocks(pdf_path), settings)

    assert [c["page"] for c in chunks] == [1, 2]


def test_chunk_pdf_blocks_merges_blocks_within_budget(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    make_pdf(pdf_path, pages=[["Short block one.", "Short block two."]])
    settings = Settings(chunk_size_tokens=650, chunk_overlap_tokens=100)

    chunks = chunk_pdf_blocks(extract_pdf_blocks(pdf_path), settings)

    assert len(chunks) == 1
    assert "Short block one" in chunks[0]["text"]
    assert "Short block two" in chunks[0]["text"]


def test_chunk_pdf_blocks_splits_when_over_budget(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    make_pdf(pdf_path, pages=[["word " * 100, "word " * 100, "word " * 100]])
    settings = Settings(chunk_size_tokens=50, chunk_overlap_tokens=10)

    chunks = chunk_pdf_blocks(extract_pdf_blocks(pdf_path), settings)

    assert len(chunks) > 1
    assert all(c["page"] == 1 for c in chunks)


def test_chunk_bbox_is_union_of_its_blocks(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    make_pdf(pdf_path, pages=[["Top block.", "Bottom block."]])
    settings = Settings(chunk_size_tokens=650, chunk_overlap_tokens=100)

    blocks = extract_pdf_blocks(pdf_path)
    chunks = chunk_pdf_blocks(blocks, settings)

    assert len(chunks) == 1
    chunk_bbox = chunks[0]["bbox"]
    assert chunk_bbox[1] == min(b["bbox"][1] for b in blocks)
    assert chunk_bbox[3] == max(b["bbox"][3] for b in blocks)


def test_load_and_chunk_pdf_sets_citation_metadata(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    make_pdf(pdf_path, pages=[["Some content."]])
    settings = Settings(chunk_size_tokens=650, chunk_overlap_tokens=100)

    documents = load_and_chunk_pdf(
        pdf_path, settings, doc_id="test-doc-id", display_name="doc.pdf"
    )

    assert len(documents) == 1
    metadata = documents[0].metadata
    assert metadata["source"] == "doc.pdf"
    assert metadata["title"] == "doc.pdf"
    assert metadata["doc_id"] == "test-doc-id"
    assert metadata["page"] == 1
    assert len(metadata["bbox"]) == 4
