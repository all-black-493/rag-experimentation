from pathlib import Path

from app.ingestion.loaders import SUPPORTED_SUFFIXES

# Signature bytes a file of this extension must start with. Office formats
# (.docx/.pptx/.xlsx) are ZIP containers, hence the shared PK signature - the
# parser rejects a ZIP that isn't the right kind of document, so this only has
# to catch the gross mismatch. Extensions absent here get a UTF-8 decodability
# check instead: plain text has no magic number.
_ZIP_MAGIC = b"PK\x03\x04"
_MAGIC_BYTES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    ".docx": _ZIP_MAGIC,
    ".pptx": _ZIP_MAGIC,
    ".xlsx": _ZIP_MAGIC,
}

_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".html",
    ".htm",
}


class UploadValidationError(ValueError):
    """Raised when an upload fails validation before parsing ever begins."""


def validate_upload(filename: str, content: bytes, max_bytes: int) -> None:
    """First line of defense: reject bad uploads before parsing sees them.

    Checks the extension is one we handle, the size is within limits, and that
    the content's actual bytes match what its extension claims - a mismatched or
    corrupt file fails fast and legibly here, instead of surfacing as an obscure
    parser exception three layers down.
    """
    if not content:
        raise UploadValidationError("File is empty.")

    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise UploadValidationError(f"File exceeds the {limit_mb}MB upload limit.")

    suffix = Path(filename).suffix.lower()

    # Checked before the magic bytes so an unknown type reports what's actually
    # wrong with it rather than passing silently for want of a signature.
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise UploadValidationError(f"Unsupported file type '{suffix}'. Supported: {supported}")

    magic = _MAGIC_BYTES.get(suffix)
    if magic is not None and not content.startswith(magic):
        raise UploadValidationError(f"File doesn't look like a valid {suffix} file.")

    if suffix in _TEXT_SUFFIXES:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("File isn't valid UTF-8 text.") from exc
