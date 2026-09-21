"""The passages an analysis points at, numbered as they are first used."""

from langchain_core.documents import Document

from app.retrieval.citations import Citation, build_citations


class SourceBook:
    def __init__(self) -> None:
        self._documents: list[Document] = []
        self._index: dict[tuple, int] = {}

    def index_of(self, document: Document) -> int:
        """The 1-based number this passage cites as; assigned on first use."""
        key = (document.metadata.get("doc_id"), document.metadata.get("chunk_index"))
        if key not in self._index:
            self._documents.append(document)
            self._index[key] = len(self._documents)
        return self._index[key]

    def citations(self) -> list[Citation]:
        return build_citations(self._documents)


_STOP = {"the", "a", "an", "of", "to", "in", "on", "and", "or", "for", "by", "at", "is", "was"}


def best_passage(text: str, candidates: list[Document]) -> Document | None:
    """The candidate sharing the most words with `text` - where a statement was read."""
    words = {w for w in _words(text) if w not in _STOP}
    if not words or not candidates:
        return None
    scored = [(len(words & set(_words(c.page_content))), i, c) for i, c in enumerate(candidates)]
    overlap, _, chosen = max(scored, key=lambda t: (t[0], -t[1]))
    return chosen if overlap else None


def _words(text: str) -> list[str]:
    return [w.strip(".,;:()[]\"'").lower() for w in text.split()]
