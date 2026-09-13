import re
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "favicons"
DOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9.-]{1,253}$")

_FALLBACK_SERVICE = "https://www.google.com/s2/favicons?sz=64&domain={domain}"
_TIMEOUT = 5.0


def _cache_paths(domain: str) -> tuple[Path, Path]:
    return CACHE_DIR / domain, CACHE_DIR / f"{domain}.ctype"


def get_cached_favicon(domain: str) -> tuple[bytes, str] | None:
    if not DOMAIN_PATTERN.match(domain):
        return None
    data_path, ctype_path = _cache_paths(domain)
    if data_path.is_file() and ctype_path.is_file():
        return data_path.read_bytes(), ctype_path.read_text().strip()
    return None


def fetch_and_cache_favicon(domain: str) -> tuple[bytes, str] | None:
    """Fetch a domain's favicon once, direct first then a favicon service, and
    cache it to disk. The cache is global, not per-tenant: a favicon carries no
    private information, so every session benefits from one fetch per domain
    rather than the "one network request per citation view" this replaces.
    """
    if not DOMAIN_PATTERN.match(domain):
        return None

    for url in (f"https://{domain}/favicon.ico", _FALLBACK_SERVICE.format(domain=domain)):
        try:
            response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if response.status_code == 200 and response.content:
            content_type = response.headers.get("content-type", "image/x-icon")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data_path, ctype_path = _cache_paths(domain)
            data_path.write_bytes(response.content)
            ctype_path.write_text(content_type)
            return response.content, content_type
    return None


def get_or_fetch_favicon(domain: str) -> tuple[bytes, str] | None:
    return get_cached_favicon(domain) or fetch_and_cache_favicon(domain)
