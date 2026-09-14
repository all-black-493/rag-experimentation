from collections.abc import Iterable
from pathlib import Path

import pymupdf
import tiktoken
from langchain_core.documents import Document

from app.config import Settings
from app.ingestion.parenting import window

_ENCODING = tiktoken.get_encoding("cl100k_base")


def extract_pdf_blocks(path: Path) -> list[dict]:
    """Extract text blocks with page-space bounding boxes, in reading order.

    A "block" is PyMuPDF's paragraph-level text grouping - the natural unit for
    citation highlighting, since it's small enough to point at precisely and
    never straddles unrelated content the way a raw page or line would.
    """
    blocks = []
    with pymupdf.open(str(path)) as doc:
        for page_number, page in enumerate(doc, start=1):
            for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
                text = text.strip()
                if not text:
                    continue
                blocks.append(
                    {
                        "text": text,
                        "page": page_number,
                        "bbox": [x0, y0, x1, y1],
                        "page_width": page.rect.width,
                        "page_height": page.rect.height,
                    }
                )
    return blocks


def _token_count(text: str) -> int:
    return len(_ENCODING.encode(text))


def _union_bbox(blocks: list[dict]) -> list[float]:
    return [
        min(b["bbox"][0] for b in blocks),
        min(b["bbox"][1] for b in blocks),
        max(b["bbox"][2] for b in blocks),
        max(b["bbox"][3] for b in blocks),
    ]


def chunk_pdf_blocks(blocks: list[dict], settings: Settings) -> list[dict]:
    """Pack blocks into token-budgeted chunks, one page per chunk.

    Chunks never span pages, so every chunk maps to exactly one page and one
    bounding box on it - what makes "jump to the cited page and highlight it"
    possible. Overlap is approximated by carrying the last block of a chunk
    into the next one, rather than an exact token count, since splitting mid-block
    would break the bbox-to-text correspondence a highlight depends on.

    Sized to `child_chunk_size_tokens`: these are the small-to-big children, so
    they stay tight enough that a bbox marks the lines that actually matched
    rather than the union of a whole page's worth of blocks.
    """
    chunk_size = settings.child_chunk_size_tokens
    overlap = settings.chunk_overlap_tokens

    chunks: list[dict] = []
    current: list[dict] = []
    current_tokens = 0

    def flush() -> None:
        if not current:
            return
        chunks.append(
            {
                "text": "\n\n".join(b["text"] for b in current),
                "page": current[0]["page"],
                "bbox": _union_bbox(current),
                "page_width": current[0]["page_width"],
                "page_height": current[0]["page_height"],
            }
        )

    for block in blocks:
        block_tokens = _token_count(block["text"])
        new_page = bool(current) and current[-1]["page"] != block["page"]
        over_budget = bool(current) and current_tokens + block_tokens > chunk_size

        if new_page or over_budget:
            overlap_block = current[-1] if (over_budget and not new_page) else None
            flush()
            if overlap_block and _token_count(overlap_block["text"]) <= overlap:
                current, current_tokens = [overlap_block], _token_count(overlap_block["text"])
            else:
                current, current_tokens = [], 0

        current.append(block)
        current_tokens += block_tokens

    flush()
    return chunks


def _attach_page_parents(chunks: list[dict], radius: int) -> None:
    """Give every chunk its parent window, grouped per page.

    Windows are built within a page rather than across the document: a chunk's
    context is the surrounding text on the same page, and a window spanning a
    page break would pull in unrelated material while the bbox still points at
    one page.
    """
    by_page: dict[int, list[dict]] = {}
    for chunk in chunks:
        by_page.setdefault(chunk["page"], []).append(chunk)

    for page_chunks in by_page.values():
        texts = [c["text"] for c in page_chunks]
        for i, chunk in enumerate(page_chunks):
            chunk["parent_text"] = window(texts, i, radius)


def render_page_thumbnails(path: Path, pages: Iterable[int], *, scale: float = 0.3) -> dict:
    """Render the given pages to small PNGs, keyed by page number.

    Only the pages asked for: a hover preview is always of a *cited* page, so
    rendering the rest would be work nothing ever reads. PNG rather than WebP -
    PyMuPDF's pixmap encoder doesn't offer WebP - and it keeps small text crisp
    where JPEG would smear it.
    """
    wanted = sorted(set(pages))
    thumbnails: dict[int, bytes] = {}
    with pymupdf.open(str(path)) as doc:
        for page_number in wanted:
            if not 1 <= page_number <= len(doc):
                continue
            pixmap = doc[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            thumbnails[page_number] = pixmap.tobytes("png")
    return thumbnails


def load_and_chunk_pdf(
    path: Path, settings: Settings, *, doc_id: str, display_name: str
) -> list[Document]:
    """Extract, chunk, and wrap a PDF's content as citation-ready Documents."""
    blocks = extract_pdf_blocks(path)
    chunks = chunk_pdf_blocks(blocks, settings)
    _attach_page_parents(chunks, settings.parent_window_radius)
    return [
        Document(
            page_content=chunk["text"],
            metadata={
                "source": display_name,
                "title": display_name,
                "source_type": "pdf",
                "page": chunk["page"],
                "doc_id": doc_id,
                "bbox": chunk["bbox"],
                "page_width": chunk["page_width"],
                "page_height": chunk["page_height"],
                "thumbnail_url": f"/files/{doc_id}/thumbnail/{chunk['page']}",
                # What the model reads; page_content stays the child so the
                # bbox keeps marking the lines that actually matched.
                "parent_text": chunk["parent_text"],
            },
        )
        for chunk in chunks
    ]
