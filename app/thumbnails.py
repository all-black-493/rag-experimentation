"""Server-side cache for web page preview images (og:image).

Same shape as app/favicons.py, and cached globally for the same reason: a page's
own social-preview image is public, so one fetch per image URL serves every
session. Fetched once at ingestion rather than when a hover card opens - a
preview that waits on a third-party request isn't a preview.

Serving the bytes ourselves rather than pointing an <img> at the origin also
keeps the viewer's browser from announcing to every cited site which documents
someone is reading.
"""

import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "thumbnails"
KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")

_TIMEOUT = 10.0
_MAX_BYTES = 3 * 1024 * 1024
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RAGIngestBot/1.0)"}


def cache_key(image_url: str) -> str:
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:32]


def _cache_paths(key: str) -> tuple[Path, Path]:
    return CACHE_DIR / key, CACHE_DIR / f"{key}.ctype"


def extract_preview_image_url(soup: BeautifulSoup, page_url: str) -> str | None:
    """Find a page's own preview image, resolved to an absolute http(s) URL."""
    for attrs in (
        {"property": "og:image"},
        {"name": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        content = tag.get("content", "").strip() if tag else ""
        if not content:
            continue
        absolute = urljoin(page_url, content)
        # http(s) only - an og:image is page-controlled, and without this a
        # crafted page could point the fetch at file:// or another scheme.
        if urlparse(absolute).scheme in {"http", "https"}:
            return absolute
    return None


def get_cached_thumbnail(key: str) -> tuple[bytes, str] | None:
    if not KEY_PATTERN.match(key):
        return None
    data_path, ctype_path = _cache_paths(key)
    if data_path.is_file() and ctype_path.is_file():
        return data_path.read_bytes(), ctype_path.read_text().strip()
    return None


def fetch_and_cache_thumbnail(image_url: str) -> str | None:
    """Fetch a preview image and cache it. Returns its cache key, or None."""
    if urlparse(image_url).scheme not in {"http", "https"}:
        return None

    try:
        response = httpx.get(
            image_url, timeout=_TIMEOUT, follow_redirects=True, headers=_HTTP_HEADERS
        )
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "")
    if (
        response.status_code != 200
        or not response.content
        or len(response.content) > _MAX_BYTES
        or not content_type.startswith("image/")
    ):
        return None

    key = cache_key(image_url)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data_path, ctype_path = _cache_paths(key)
    data_path.write_bytes(response.content)
    ctype_path.write_text(content_type)
    return key
