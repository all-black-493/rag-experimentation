"""Rebuild whole documents from the corpus's pre-cut chunks.

The corpus arrives already split into 800-character windows with a fixed
150-character overlap, cut wherever the counter landed - four times out of five
mid-word. Indexing those as-is would mean embedding fragments that start and end
in the middle of a sentence, and citing them to a reader.

Because the overlap is fixed, the split is reversible: the document is the first
window plus every later window minus its first 150 characters. Each join is
checked rather than assumed - if a window doesn't overlap its predecessor as
expected, the two are joined with a line break instead, and the document is
flagged so an ingest run can report how many needed that.

Reconstructed text then goes through the same sentence-aware, small-to-big
chunker as everything else in the pipeline.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from app.corpus.courts import court_name
from app.corpus.ids import content_id
from app.metadata import Collection

# The corpus's window overlap. Measured, not assumed: 14,136 of 14,150 sampled
# consecutive pairs overlapped by exactly this many characters.
OVERLAP = 150

# Below this, a shorter-than-expected overlap is more likely coincidence than a
# real join, and the fallback separator is the safer choice.
_MIN_OVERLAP = 20

_URL = re.compile(
    r"/akn/ke/(?P<kind>judgment|act)/(?P<rest>[^@]+?)(?:/eng@(?P<version>\d{4}-\d{2}-\d{2}))?$"
)
_DATE_FORMATS = ("%B %d, %Y", "%d %B %Y", "%Y-%m-%d")


@dataclass(frozen=True)
class SourceDocument:
    """One whole document from the corpus, with its provenance parsed out."""

    collection: Collection
    doc_id: str
    url: str
    title: str
    text: str
    # Judgments only.
    court_code: str | None = None
    court: str | None = None
    decision_date: date | None = None
    # Judgments: year decided. Acts: year enacted. What a year filter means.
    year: int | None = None
    # The point-in-time version Kenya Law served. An Act amended later gets a
    # new version date, a new URL, and therefore a new doc_id.
    version_date: date | None = None
    # How many windows had to be joined with a separator rather than by overlap.
    fallback_joins: int = 0


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.replace("\xa0", " ").strip()
    for fmt in _DATE_FORMATS:
        try:
            # A calendar date, not an instant: no timezone applies.
            return datetime.strptime(value, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _provenance(url: str, metadata: dict) -> dict:
    """Everything the URL and row metadata tell us about where a document came from."""
    match = _URL.search(url)
    if match is None:
        return {}

    version = match.group("version")
    version_date = date.fromisoformat(version) if version else None
    segments = match.group("rest").split("/")

    if match.group("kind") == "judgment":
        code = segments[0]
        decided = parse_date(metadata.get("date"))
        year = decided.year if decided else _first_year(segments)
        return {
            "court_code": code,
            "court": court_name(code),
            "decision_date": decided,
            "year": year,
            "version_date": version_date,
        }

    return {"year": _first_year(segments), "version_date": version_date}


def _first_year(segments: list[str]) -> int | None:
    for segment in segments:
        if re.fullmatch(r"(19|20)\d\d", segment):
            return int(segment)
    return None


def join_windows(windows: list[str], overlap: int = OVERLAP) -> tuple[str, int]:
    """Stitch overlapping windows back into one text. Returns (text, fallback joins).

    Each join is verified: the next window must begin with what the text so far
    ends with. When it doesn't, a shorter overlap is tried before giving up and
    joining on a line break - wrong joins would silently corrupt the document,
    and a visible seam is the lesser harm.
    """
    if not windows:
        return "", 0

    text = windows[0]
    fallbacks = 0
    for window in windows[1:]:
        # A window that is entirely overlap carries nothing new.
        if len(window) <= overlap and text.endswith(window):
            continue
        matched = _overlap_length(text, window, overlap)
        if matched is None:
            text = f"{text}\n{window}"
            fallbacks += 1
        else:
            text += window[matched:]
    return text, fallbacks


def _overlap_length(text: str, window: str, expected: int) -> int | None:
    """How many leading characters of `window` repeat the tail of `text`, if any."""
    if text.endswith(window[:expected]):
        return expected
    # The last window of a document can be shorter than a full overlap, and a
    # handful of pairs in the corpus overlap by a different amount.
    for k in range(min(len(window), expected * 2), _MIN_OVERLAP - 1, -1):
        if k != expected and text.endswith(window[:k]):
            return k
    return None


def reconstruct(rows: list[dict]) -> list[SourceDocument]:
    """Group corpus rows by URL and rebuild each document. Deterministic order."""
    by_url: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        # Keyed by chunk_id, so the corpus's exact-duplicate rows collapse.
        by_url[row["metadata"]["url"]][row["chunk_id"]] = row

    documents = []
    for url in sorted(by_url):
        chunks = sorted(by_url[url].values(), key=lambda r: r["metadata"]["chunk_index"])
        metadata = chunks[0]["metadata"]
        text, fallbacks = join_windows([c["text"] for c in chunks])
        collection: Collection = "case_law" if metadata["type"] == "case_law" else "legislation"
        documents.append(
            SourceDocument(
                collection=collection,
                doc_id=content_id(url),
                url=url,
                title=metadata.get("title", "").replace("\xa0", " ").strip() or url,
                text=text,
                fallback_joins=fallbacks,
                **_provenance(url, metadata),
            )
        )
    return documents
