"""Content-addressed ingestion, so the same bytes are never indexed twice.

The doc id is a hash of the file's content rather than a fresh uuid4 per upload.
Re-uploading the same document therefore lands on the same id, and the pipeline
can skip straight past parsing, chunking and - the expensive part - embedding.

That also makes ingestion idempotent: a retried request, a double-clicked upload
button, or a replayed job produces one indexed copy, not several. Without it the
retry logic elsewhere in this pipeline would quietly multiply documents.

Scoped per tenant: two sessions uploading the same file each get their own
indexed copy, because deleting one must not remove the other's, and neither
should be able to infer the other's existence from a dedupe hit.
"""

import hashlib
import json
from pathlib import Path

_MANIFEST_NAME = "ingested.json"


def content_id(content: bytes) -> str:
    """Stable id for a document's bytes. Truncated to keep ids path-friendly."""
    return hashlib.sha256(content).hexdigest()[:32]


def _manifest_path(uploads_dir: Path, tenant: str) -> Path:
    return uploads_dir / tenant / _MANIFEST_NAME


def _read_manifest(uploads_dir: Path, tenant: str) -> dict:
    path = _manifest_path(uploads_dir, tenant)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        # A truncated manifest means re-ingesting, which is wasteful but correct.
        # Failing the upload instead would be worse.
        return {}


def already_ingested(uploads_dir: Path, tenant: str, doc_id: str) -> dict | None:
    """The prior ingestion record for this content, if this tenant has one."""
    return _read_manifest(uploads_dir, tenant).get(doc_id)


def record_ingestion(
    uploads_dir: Path, tenant: str, doc_id: str, *, source: str, chunks: int
) -> None:
    manifest = _read_manifest(uploads_dir, tenant)
    manifest[doc_id] = {"source": source, "chunks": chunks}

    tenant_dir = uploads_dir / tenant
    tenant_dir.mkdir(parents=True, exist_ok=True)
    # Write-then-replace: a crash mid-write leaves the old manifest intact rather
    # than a half-written one that reads as "nothing was ever ingested".
    temporary = tenant_dir / f"{_MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(manifest, indent=2))
    temporary.replace(_manifest_path(uploads_dir, tenant))
