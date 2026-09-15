import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

# Must match what app.ingestion.dedupe.content_id produces - a truncated sha256,
# not a uuid. Every doc_id arriving from a request is checked against this before
# it is used to build a path, so it can never walk out of the tenant's directory.
DOC_ID_PATTERN = re.compile(r"^[0-9a-f]{40}$")


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


def delete_document_files(tenant: str, doc_id: str) -> int:
    """Remove a document's stored PDF and every page thumbnail. Returns files removed.

    Thumbnails are globbed rather than enumerated: only cited pages are rendered,
    so how many exist isn't knowable from the doc_id alone.
    """
    if not DOC_ID_PATTERN.match(doc_id):
        return 0

    tenant_dir = UPLOADS_DIR / tenant
    removed = 0
    for path in [tenant_dir / f"{doc_id}.pdf", *tenant_dir.glob(f"{doc_id}.p*.png")]:
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            # A non-PDF source has no stored file; nothing to remove.
            pass
        except OSError:
            # One file we can't remove shouldn't abort the rest of the deletion.
            logger.warning("could not remove %s", path, exc_info=True)
    return removed
