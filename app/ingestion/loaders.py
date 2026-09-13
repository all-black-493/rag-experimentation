from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document

from app.ingestion.normalize import normalize
from app.thumbnails import extract_preview_image_url, fetch_and_cache_thumbnail

_HTTP_TIMEOUT = 30.0
# Many sites (Wikipedia included) reject requests with no User-Agent at all.
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RAGIngestBot/1.0)"}


def _document(path: Path, text: str) -> Document:
    """Wrap extracted text with provenance, normalizing on the way through.

    Every file loader goes through here so normalization can't be forgotten when
    a new format is added.
    """
    return Document(
        page_content=normalize(text),
        metadata={"source": str(path), "title": path.name, "source_type": "text"},
    )


def load_text(path: Path) -> list[Document]:
    """Load a plain-text or Markdown file as a single Document."""
    return [_document(path, path.read_text(encoding="utf-8"))]


def load_web(url: str) -> list[Document]:
    """Fetch a web page and extract its visible text content."""
    response = httpx.get(
        url, timeout=_HTTP_TIMEOUT, follow_redirects=True, headers=_HTTP_HEADERS
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Before decompose() strips <header>, which is where og: tags often live.
    image_url = extract_preview_image_url(soup, url)
    thumbnail_key = fetch_and_cache_thumbnail(image_url) if image_url else None

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url
    text = normalize(soup.get_text(separator="\n", strip=True))
    domain = urlparse(url).netloc
    metadata = {
        "source": url,
        "title": title,
        "source_type": "web",
        "favicon_url": f"/favicons/{domain}" if domain else None,
        "thumbnail_url": f"/thumbnails/{thumbnail_key}" if thumbnail_key else None,
    }
    return [Document(page_content=text, metadata=metadata)]


def load_docx(path: Path) -> list[Document]:
    """Paragraphs and table cells from a Word document, in document order."""
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return [_document(path, "\n\n".join(parts))]


def load_pptx(path: Path) -> list[Document]:
    """Slide text, one block per slide so a chunk keeps a slide's context together."""
    from pptx import Presentation

    slides = []
    for number, slide in enumerate(Presentation(str(path)).slides, start=1):
        lines = [
            shape.text.strip()
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text.strip()
        ]
        if lines:
            slides.append(f"[Slide {number}]\n" + "\n".join(lines))

    return [_document(path, "\n\n".join(slides))]


def load_xlsx(path: Path) -> list[Document]:
    """Spreadsheet cells as delimited rows, sheet by sheet.

    read_only + values_only so a large workbook doesn't get fully materialised,
    and so formulas come through as their computed values rather than as source.
    """
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    try:
        sections = []
        for sheet in workbook.worksheets:
            rows = [
                " | ".join("" if cell is None else str(cell) for cell in row).strip(" |")
                for row in sheet.iter_rows(values_only=True)
            ]
            rows = [row for row in rows if row.strip()]
            if rows:
                sections.append(f"[Sheet: {sheet.title}]\n" + "\n".join(rows))
    finally:
        workbook.close()

    return [_document(path, "\n\n".join(sections))]


def load_csv(path: Path) -> list[Document]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        rows = [" | ".join(row) for row in csv.reader(handle) if any(f.strip() for f in row)]
    return [_document(path, "\n".join(rows))]


def load_json(path: Path) -> list[Document]:
    """Pretty-printed JSON.

    Re-dumping rather than passing the raw text through gives consistent
    indentation for chunking, and fails loudly here on malformed JSON instead of
    silently indexing a broken file as prose.
    """
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return [_document(path, json.dumps(data, indent=2, ensure_ascii=False))]


def load_html(path: Path) -> list[Document]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else path.name
    document = _document(path, soup.get_text(separator="\n", strip=True))
    document.metadata["title"] = title
    return [document]


_LOADERS_BY_SUFFIX = {
    ".txt": load_text,
    ".md": load_text,
    ".markdown": load_text,
    ".rst": load_text,
    ".log": load_text,
    ".docx": load_docx,
    ".pptx": load_pptx,
    ".xlsx": load_xlsx,
    ".csv": load_csv,
    ".tsv": load_csv,
    ".json": load_json,
    ".html": load_html,
    ".htm": load_html,
}

SUPPORTED_SUFFIXES = frozenset(_LOADERS_BY_SUFFIX) | {".pdf"}


def load_path(path: Path) -> list[Document]:
    """Dispatch to the right loader based on file extension.

    PDFs aren't here - app.ingestion.pdf handles them separately, since they need
    bounding-box-aware chunking and file persistence that this generic path doesn't.
    """
    loader = _LOADERS_BY_SUFFIX.get(path.suffix.lower())
    if loader is None:
        supported = ", ".join(sorted(_LOADERS_BY_SUFFIX))
        raise ValueError(f"Unsupported file type '{path.suffix}'. Supported: {supported}, .pdf")
    return loader(path)
