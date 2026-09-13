from pathlib import Path

# Signature bytes a file of this extension must start with. Extensions absent
# here (.txt/.md/.markdown) get a UTF-8 decodability check instead - plain text
# has no magic number to check.
_MAGIC_BYTES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
}

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


class UploadValidationError(ValueError):
    """Raised when an upload fails validation before parsing ever begins."""


def validate_upload(filename: str, content: bytes, max_bytes: int) -> None:
    """First line of defense: reject bad uploads before parsing sees them.

    Checks size and that the content's actual bytes match what its extension
    claims - a mismatched or corrupt file fails fast and legibly here, instead
    of surfacing as an obscure parser exception three layers down.
    """
    if not content:
        raise UploadValidationError("File is empty.")

    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise UploadValidationError(f"File exceeds the {limit_mb}MB upload limit.")

    suffix = Path(filename).suffix.lower()

    magic = _MAGIC_BYTES.get(suffix)
    if magic is not None and not content.startswith(magic):
        raise UploadValidationError(f"File doesn't look like a valid {suffix} file.")

    if suffix in _TEXT_SUFFIXES:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("File isn't valid UTF-8 text.") from exc
