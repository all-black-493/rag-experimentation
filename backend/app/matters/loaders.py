"""Text out of the formats a matter accepts, and the checks before parsing."""

from pathlib import Path

from app.corpus.normalize import normalize
from app.matters.models import DocumentKind

KINDS: dict[str, DocumentKind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "text",
    ".md": "text",
}

# What a file of this extension must start with. Office documents are ZIP
# containers; a ZIP that isn't a Word document fails in the parser instead.
_MAGIC = {".pdf": b"%PDF-", ".docx": b"PK\x03\x04"}


class UploadError(ValueError):
    """The upload is refused before anything is parsed or stored."""


def kind_of(name: str) -> DocumentKind:
    suffix = Path(name).suffix.lower()
    try:
        return KINDS[suffix]
    except KeyError:
        supported = ", ".join(sorted(KINDS))
        raise UploadError(f"Unsupported file type {suffix!r}. Supported: {supported}") from None


def validate(name: str, content: bytes, max_bytes: int) -> DocumentKind:
    """Refuse an empty, oversized, mistyped or non-text file while the user is watching."""
    kind = kind_of(name)
    if not content:
        raise UploadError("The file is empty.")
    if len(content) > max_bytes:
        raise UploadError(f"The file is over the {max_bytes // (1024 * 1024)} MB limit.")
    suffix = Path(name).suffix.lower()
    magic = _MAGIC.get(suffix)
    if magic is not None and not content.startswith(magic):
        raise UploadError(f"The file doesn't look like a {suffix} file.")
    if kind == "text":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadError("The file isn't UTF-8 text.") from exc
    return kind


def load_text(path: Path) -> str:
    return normalize(path.read_text(encoding="utf-8"))


def load_docx(path: Path) -> str:
    """Paragraphs and table cells in document order."""
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return normalize("\n\n".join(parts))
