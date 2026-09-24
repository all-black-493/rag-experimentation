"""Where matters live: one directory per matter, a JSON record and the files.

A JSON file per matter rather than a database: a matter is a name and a few
documents, read on every request to a matter and written a handful of times
per upload. Writes go through a temporary file and a rename, so a crash never
leaves a half-written record that reads as an empty matter.

Ids are path components, so every one that arrives from a request is checked
against its pattern before it is used to build a path.
"""

import re
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.analysis.models import CaseAnalysis
from app.matters.models import Matter, MatterDocument

MATTER_ID = re.compile(r"^[0-9a-f]{12}$")
# The content hash app.corpus.ids.content_id produces.
DOC_ID = re.compile(r"^[0-9a-f]{40}$")

_RECORD = "matter.json"


def new_matter_id() -> str:
    return secrets.token_hex(6)


class MatterStore:
    def __init__(self, root: Path, on_change: Callable[[Matter], None] | None = None):
        self._root = root
        self._lock = threading.Lock()
        # Every state change goes through `_write`, so that is where anyone
        # watching a matter hears about it.
        self._on_change = on_change

    def _dir(self, matter_id: str) -> Path:
        if not MATTER_ID.match(matter_id):
            raise ValueError(f"malformed matter id {matter_id!r}")
        return self._root / matter_id

    def create(self, name: str) -> Matter:
        matter = Matter(id=new_matter_id(), name=name.strip())
        self._write(matter)
        return matter

    def get(self, matter_id: str) -> Matter | None:
        if not MATTER_ID.match(matter_id):
            return None
        path = self._root / matter_id / _RECORD
        if not path.is_file():
            return None
        return Matter.model_validate_json(path.read_text())

    def list(self) -> list[Matter]:
        if not self._root.is_dir():
            return []
        matters = [m for d in self._root.iterdir() if (m := self.get(d.name)) is not None]
        return sorted(matters, key=lambda m: m.updated_at, reverse=True)

    def delete(self, matter_id: str) -> bool:
        directory = self._dir(matter_id)
        if not directory.is_dir():
            return False
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
        return True

    def add_document(self, matter_id: str, document: MatterDocument) -> Matter:
        """Attach a document record, replacing any previous record with the same id."""
        with self._lock:
            matter = self._require(matter_id)
            matter.documents = [d for d in matter.documents if d.doc_id != document.doc_id]
            matter.documents.append(document)
            self._write(matter)
            return matter

    def update_document(self, matter_id: str, doc_id: str, **fields) -> MatterDocument:
        """Change one document's record in place: status, counts, profile, error."""
        with self._lock:
            matter = self._require(matter_id)
            document = matter.document(doc_id)
            if document is None:
                raise KeyError(doc_id)
            updated = document.model_copy(update=fields)
            matter.documents = [updated if d.doc_id == doc_id else d for d in matter.documents]
            self._write(matter)
            return updated

    def set_topics(self, matter_id: str, count: int, error: str | None = None) -> Matter:
        with self._lock:
            matter = self._require(matter_id)
            matter.topics = count
            matter.topics_error = error
            self._write(matter)
            return matter

    def set_analysis(self, matter_id: str, analysis: CaseAnalysis | None) -> Matter:
        with self._lock:
            matter = self._require(matter_id)
            matter.analysis = analysis
            self._write(matter)
            return matter

    def remove_document(self, matter_id: str, doc_id: str) -> bool:
        with self._lock:
            matter = self._require(matter_id)
            if matter.document(doc_id) is None:
                return False
            matter.documents = [d for d in matter.documents if d.doc_id != doc_id]
            self._write(matter)
        for path in self._dir(matter_id).glob(f"{doc_id}.*"):
            path.unlink()
        return True

    def save_file(self, matter_id: str, doc_id: str, suffix: str, content: bytes) -> Path:
        """Keep the original bytes: a PDF citation opens the page it came from."""
        path = self._dir(matter_id) / f"{doc_id}{suffix}"
        path.write_bytes(content)
        return path

    def file_path(self, matter_id: str, doc_id: str) -> Path | None:
        """The stored original, or None for an unknown or malformed id."""
        if not MATTER_ID.match(matter_id) or not DOC_ID.match(doc_id):
            return None
        return next(iter(self._dir(matter_id).glob(f"{doc_id}.*")), None)

    def _require(self, matter_id: str) -> Matter:
        matter = self.get(matter_id)
        if matter is None:
            raise KeyError(matter_id)
        return matter

    def _write(self, matter: Matter) -> None:
        matter.updated_at = datetime.now(UTC)
        directory = self._dir(matter.id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"{_RECORD}.tmp"
        temporary.write_text(matter.model_dump_json(indent=2))
        temporary.replace(directory / _RECORD)
        if self._on_change is not None:
            self._on_change(matter)
