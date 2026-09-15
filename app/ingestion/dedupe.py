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


# Truncated to keep ids path-friendly, but deliberately not to 32 - at that
# length a hex digest parses as a UUID, and Weaviate's autoschema then types
# doc_id as its native `uuid` and hands the value back in canonical dashed form.
# The id a citation carried would no longer be the id the file was stored under,
# so every PDF citation would open a 404. 40 hex characters cannot be read as a
# UUID, so what goes in is what comes back out.
_ID_LENGTH = 40


def content_id(content: bytes) -> str:
    """Stable id for a document's bytes."""
    return hashlib.sha256(content).hexdigest()[:_ID_LENGTH]


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


def list_ingested(uploads_dir: Path, tenant: str) -> list[dict]:
    """Everything this tenant has indexed, most recent first.

    The manifest is the record of what a session put in, so it - not a scan of
    the vector store - is what the sources list is built from. Entries are only
    written after a successful index, so nothing here is a document the user
    can't actually query.
    """
    manifest = _read_manifest(uploads_dir, tenant)
    return [{"doc_id": doc_id, **entry} for doc_id, entry in reversed(manifest.items())]


def forget_ingestion(uploads_dir: Path, tenant: str, doc_id: str) -> bool:
    """Drop a document's record. Returns whether there was one.

    Deleting a document has to include this: while the record stands, re-uploading
    the same file hashes to the same id, hits the dedupe check, and is skipped -
    so the user could never add back what they removed.
    """
    manifest = _read_manifest(uploads_dir, tenant)
    if manifest.pop(doc_id, None) is None:
        return False
    _write_manifest(uploads_dir, tenant, manifest)
    return True


def record_ingestion(
    uploads_dir: Path, tenant: str, doc_id: str, *, source: str, source_type: str, chunks: int
) -> None:
    manifest = _read_manifest(uploads_dir, tenant)
    manifest[doc_id] = {"source": source, "source_type": source_type, "chunks": chunks}
    _write_manifest(uploads_dir, tenant, manifest)


def _write_manifest(uploads_dir: Path, tenant: str, manifest: dict) -> None:
    tenant_dir = uploads_dir / tenant
    tenant_dir.mkdir(parents=True, exist_ok=True)
    # Write-then-replace: a crash mid-write leaves the old manifest intact rather
    # than a half-written one that reads as "nothing was ever ingested".
    temporary = tenant_dir / f"{_MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(manifest, indent=2))
    temporary.replace(_manifest_path(uploads_dir, tenant))
