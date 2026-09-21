"""Quality signals computed from an answer, with no second LLM call.

These are deterministic and cheap, so every request can carry them. They answer
"is this answer actually anchored to the retrieved evidence" structurally - not
whether the claims are true, which is what the groundedness check and the offline
ragas eval are for.
"""

import re
from dataclasses import dataclass

# Sentence boundary: terminator followed by whitespace. Markers sit before the
# terminator ("... 7-ALPHA-99 [1]."), so they stay with their own sentence.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
# At most three digits: a four-digit bracketed number is the year in a neutral
# citation - "Republic v Mgunya [2010] eKLR" - not a reference to a passage.
# Treating it as one would strip real case names from legal answers.
_CITATION_MARKER = re.compile(r"\[(\d{1,3})\]")
# Leading markdown list/heading punctuation, so "- foo" measures as "foo".
_LIST_PREFIX = re.compile(r"^\s*(?:[-*+]|\d+\.|#{1,6})\s*")

# Tidying up after a removed citation marker.
_MANY_SPACES_INLINE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])")


@dataclass(frozen=True)
class CoverageReport:
    coverage: float
    sentences: int
    cited_sentences: int
    cited_indices: list[int]
    unused_citations: list[int]
    invalid_indices: list[int]


def _sentences(answer: str) -> list[str]:
    candidates = []
    for line in answer.splitlines():
        stripped = _LIST_PREFIX.sub("", line).strip()
        if stripped:
            candidates.extend(part for part in _SENTENCE_BOUNDARY.split(stripped) if part.strip())
    return candidates


def strip_invalid_citations(answer: str, citation_count: int) -> tuple[str, list[int]]:
    """Remove `[n]` markers that point at citations which don't exist.

    The generator occasionally emits a marker past the end of the context it was
    given. Left in, it renders as a citation the reader can click and a number
    they can't check - the failure mode this whole citation contract exists to
    prevent. Scoring records that it happened; this stops it reaching anyone.

    Only the marker is removed, never the surrounding claim: the sentence may
    well be supported, and silently deleting text would be a worse trade. An
    answer that loses all its markers simply scores zero coverage.
    """
    removed: list[int] = []

    def replace(match: re.Match) -> str:
        index = int(match.group(1))
        if 1 <= index <= citation_count:
            return match.group(0)
        removed.append(index)
        return ""

    cleaned = _CITATION_MARKER.sub(replace, answer)
    if not removed:
        return answer, []

    # Tidy the space left where a marker was, e.g. "text [1] [7]." -> "text [1]."
    cleaned = _MANY_SPACES_INLINE.sub(" ", cleaned)
    cleaned = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", cleaned)
    return cleaned.strip(), sorted(set(removed))


def citation_coverage(answer: str, citation_count: int) -> CoverageReport:
    """How much of an answer is anchored to a citation.

    `coverage` is the share of sentences carrying at least one `[n]` marker.
    `invalid_indices` catches markers pointing outside the citations actually
    returned - a marker the model invented rather than took from the context.
    """
    sentences = _sentences(answer)
    cited_sentences = 0
    used: set[int] = set()
    invalid: set[int] = set()

    for sentence in sentences:
        markers = [int(n) for n in _CITATION_MARKER.findall(sentence)]
        if markers:
            cited_sentences += 1
        for marker in markers:
            (used if 1 <= marker <= citation_count else invalid).add(marker)

    return CoverageReport(
        coverage=cited_sentences / len(sentences) if sentences else 0.0,
        sentences=len(sentences),
        cited_sentences=cited_sentences,
        cited_indices=sorted(used),
        unused_citations=sorted(set(range(1, citation_count + 1)) - used),
        invalid_indices=sorted(invalid),
    )
