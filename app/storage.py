import re
from pathlib import Path

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

DOC_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def save_pdf(tenant: str, doc_id: str, content: bytes) -> Path:
    """Persist an uploaded PDF so its pages can be viewed later from a citation."""
    tenant_dir = UPLOADS_DIR / tenant
    tenant_dir.mkdir(parents=True, exist_ok=True)
    path = tenant_dir / f"{doc_id}.pdf"
    path.write_bytes(content)
    return path


def get_pdf_path(tenant: str, doc_id: str) -> Path | None:
    """Resolve a stored PDF's path, scoped to the requesting tenant.

    Returns None for a malformed doc_id (never touches the filesystem with an
    unvalidated path) and for a doc_id that exists under a different tenant -
    both cases look identical to the caller, a plain "not found."
    """
    if not DOC_ID_PATTERN.match(doc_id):
        return None
    path = UPLOADS_DIR / tenant / f"{doc_id}.pdf"
    return path if path.is_file() else None


def save_page_thumbnail(tenant: str, doc_id: str, page: int, content: bytes) -> Path:
    """Persist one page's thumbnail, rendered once at ingestion."""
    tenant_dir = UPLOADS_DIR / tenant
    tenant_dir.mkdir(parents=True, exist_ok=True)
    path = tenant_dir / f"{doc_id}.p{page}.png"
    path.write_bytes(content)
    return path


def get_page_thumbnail_path(tenant: str, doc_id: str, page: int) -> Path | None:
    """Resolve a page thumbnail, with the same tenant scoping as the PDF itself."""
    if not DOC_ID_PATTERN.match(doc_id) or page < 1:
        return None
    path = UPLOADS_DIR / tenant / f"{doc_id}.p{page}.png"
    return path if path.is_file() else None
