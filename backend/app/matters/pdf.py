"""PDF text with the page and box each chunk came from.

A chunk from a PDF never spans a page, and carries the union of its blocks'
bounding boxes: that is what lets a citation open the page and draw the
highlight where the words are. Chunks are packed from PyMuPDF's blocks -
paragraph-level groupings in reading order - rather than cut by character
count, because splitting mid-block would break the box-to-text correspondence.
"""

from pathlib import Path

import pymupdf
import tiktoken
from langchain_core.documents import Document

from app.config import Settings
from app.corpus.normalize import normalize
from app.corpus.parenting import window

_ENCODING = tiktoken.get_encoding("cl100k_base")


def page_count(path: Path) -> int:
    with pymupdf.open(str(path)) as doc:
        return len(doc)


def extract_blocks(path: Path) -> list[dict]:
    """Text blocks with page-space bounding boxes, in reading order."""
    blocks = []
    with pymupdf.open(str(path)) as doc:
        for page_number, page in enumerate(doc, start=1):
            for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
                # A block is a paragraph; its line breaks are layout, not content.
                text = normalize(" ".join(text.split("\n")))
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


def _tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _union(blocks: list[dict]) -> list[float]:
    return [
        min(b["bbox"][0] for b in blocks),
        min(b["bbox"][1] for b in blocks),
        max(b["bbox"][2] for b in blocks),
        max(b["bbox"][3] for b in blocks),
    ]


def pack_blocks(blocks: list[dict], chunk_tokens: int, overlap_tokens: int) -> list[dict]:
    """Pack blocks into token-budgeted chunks, one page per chunk.

    Overlap is a whole block carried into the next chunk when it fits the
    overlap budget, rather than an exact token count - the box has to keep
    describing the text.
    """
    chunks: list[dict] = []
    current: list[dict] = []
    current_tokens = 0

    def flush() -> None:
        if current:
            chunks.append(
                {
                    "text": "\n\n".join(b["text"] for b in current),
                    "page": current[0]["page"],
                    "bbox": _union(current),
                    "page_width": current[0]["page_width"],
                    "page_height": current[0]["page_height"],
                }
            )

    for block in blocks:
        block_tokens = _tokens(block["text"])
        new_page = bool(current) and current[-1]["page"] != block["page"]
        over_budget = bool(current) and current_tokens + block_tokens > chunk_tokens
        if new_page or over_budget:
            carried = current[-1] if over_budget and not new_page else None
            flush()
            if carried is not None and _tokens(carried["text"]) <= overlap_tokens:
                current, current_tokens = [carried], _tokens(carried["text"])
            else:
                current, current_tokens = [], 0
        current.append(block)
        current_tokens += block_tokens
    flush()
    return chunks


def chunk_pdf(path: Path, settings: Settings) -> list[Document]:
    """Chunks with page, box and a parent window built within the page.

    Windows stay on the page: a chunk's context is the text around it there,
    and a window across a page break would read as one thing while the box
    points at another.
    """
    chunks = pack_blocks(
        extract_blocks(path), settings.child_chunk_size_tokens, settings.chunk_overlap_tokens
    )
    by_page: dict[int, list[dict]] = {}
    for chunk in chunks:
        by_page.setdefault(chunk["page"], []).append(chunk)
    for page_chunks in by_page.values():
        texts = [c["text"] for c in page_chunks]
        for i, chunk in enumerate(page_chunks):
            chunk["parent_text"] = window(texts, i, settings.parent_window_radius)

    return [
        Document(
            page_content=chunk["text"],
            metadata={
                "chunk_index": index,
                "page": chunk["page"],
                "bbox": chunk["bbox"],
                "page_width": chunk["page_width"],
                "page_height": chunk["page_height"],
                "parent_text": chunk["parent_text"],
            },
        )
        for index, chunk in enumerate(chunks)
    ]
