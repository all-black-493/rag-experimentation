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
_CITATION_MARKER = re.compile(r"\[(\d+)\]")
# Leading markdown list/heading punctuation, so "- foo" measures as "foo".
_LIST_PREFIX = re.compile(r"^\s*(?:[-*+]|\d+\.|#{1,6})\s*")


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
