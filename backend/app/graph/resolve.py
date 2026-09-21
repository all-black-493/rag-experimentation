"""Turn a citation as written into a document in the corpus, when there is one.

Judgments carry their own neutral citation and case number in their title, so
both forms resolve exactly. Acts resolve by title. A citation to something the
corpus doesn't hold - an older law report, an unindexed Act - stays unresolved:
the edge is still recorded (a lawyer wants to know what was cited) but points
at nothing retrievable.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

from app.graph.refs import Reference, case_number_key, neutral_key, normalise_title, parties_key
from app.metadata import Collection

_TITLE_NEUTRAL = re.compile(r"\[((?:19|20)\d\d)\]\s*(KE[A-Z]{2,5})\s*(\d+)")
_TITLE_PARTIES = re.compile(r"^(?P<parties>.+?\sv\s.+?)\s*\(")
_TITLE_CASE_NUMBER = re.compile(
    r"\(((?:[A-Z][A-Za-z]+\s)*?(?:Appeal|Application|Case|Cause|Petition|Suit|Reference|Revision|Offence))\s+"
    r"(?:No\.?\s*)?(E?\d+[A-Z]?)\s+of\s+((?:19|20)\d\d)"
)


@dataclass(frozen=True)
class IndexedDocument:
    doc_id: str
    collection: Collection
    title: str
    url: str


class Resolver:
    """Lookup tables from the corpus's own titles."""

    def __init__(self, documents: list[IndexedDocument]):
        self.by_id = {d.doc_id: d for d in documents}
        self._neutral: dict[str, str] = {}
        self._case_number: dict[str, list[str]] = defaultdict(list)
        self._parties: dict[str, list[str]] = defaultdict(list)
        self._statute: dict[str, str] = {}
        for doc in documents:
            title = doc.title.replace("\xa0", " ")
            if doc.collection == "case_law":
                if m := _TITLE_NEUTRAL.search(title):
                    self._neutral[neutral_key(m.group(1), m.group(2), m.group(3))] = doc.doc_id
                if m := _TITLE_CASE_NUMBER.search(title):
                    self._case_number[case_number_key(m.group(1), m.group(2), m.group(3))].append(
                        doc.doc_id
                    )
                if m := _TITLE_PARTIES.search(title):
                    self._parties[parties_key(m["parties"])].append(doc.doc_id)
            else:
                self._statute.setdefault(normalise_title(title), doc.doc_id)
                if doc.url.endswith("/constitution"):
                    self._statute["Constitution of Kenya"] = doc.doc_id
                    self._statute["Constitution"] = doc.doc_id

    def resolve(self, reference: Reference) -> str | None:
        if reference.kind == "case":
            if reference.key in self._neutral:
                return self._neutral[reference.key]
            # Case numbers and party names repeat; only a unique match is trusted.
            candidates = self._case_number.get(reference.key, [])
            if not candidates and reference.parties:
                candidates = self._parties.get(parties_key(reference.parties), [])
            return candidates[0] if len(candidates) == 1 else None
        return self._statute.get(reference.key)
