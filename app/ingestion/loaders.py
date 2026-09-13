from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_core.documents import Document

from app.thumbnails import extract_preview_image_url, fetch_and_cache_thumbnail

_HTTP_TIMEOUT = 30.0
# Many sites (Wikipedia included) reject requests with no User-Agent at all.
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RAGIngestBot/1.0)"}


def load_text(path: Path) -> list[Document]:
    """Load a plain-text or Markdown file as a single Document."""
    text = path.read_text(encoding="utf-8")
    metadata = {"source": str(path), "title": path.name, "source_type": "text"}
    return [Document(page_content=text, metadata=metadata)]


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
    text = soup.get_text(separator="\n", strip=True)
    domain = urlparse(url).netloc
    metadata = {
        "source": url,
        "title": title,
        "source_type": "web",
        "favicon_url": f"/favicons/{domain}" if domain else None,
        "thumbnail_url": f"/thumbnails/{thumbnail_key}" if thumbnail_key else None,
    }
    return [Document(page_content=text, metadata=metadata)]


_LOADERS_BY_SUFFIX = {
    ".txt": load_text,
    ".md": load_text,
    ".markdown": load_text,
}


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
