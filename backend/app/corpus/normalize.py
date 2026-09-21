"""Text normalization, run between parsing and chunking.

Extracted text carries artefacts of the format it came from - PDFs hyphenate
across line breaks, Office formats and web pages bring non-breaking spaces and
smart quotes, and everything produces ragged blank lines. Left alone these leak
into chunks, where they cost embedding tokens, break exact-match keyword search
in the hybrid query, and show up verbatim in the quoted text of a citation.

Deliberately conservative: it does not lowercase, strip punctuation, or collapse
single newlines. Chunking and bounding-box highlighting both depend on the text
staying recognisably the same as what the source document says.
"""

import re
import unicodedata

# Soft hyphen, zero-width space/non-joiner/joiner, BOM. Written as escapes
# because they're invisible in source - pasted literally they survive review
# unnoticed while still splitting tokens.
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\ufeff"))

# "inter-\nnational" -> "international". Only when a lowercase letter precedes
# the hyphen and follows the break, which is the PDF line-wrap case; it leaves
# genuine compounds like "well-\nknown" alone only by accident, so keep the
# rule narrow rather than clever.
_LINEBREAK_HYPHEN = re.compile(r"(\w)-\n(\w)")

_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
_MANY_SPACES = re.compile(r"[ \t]{2,}")


def normalize(text: str) -> str:
    """Clean extracted text without changing what it says."""
    # NFKC folds ligatures (ﬁ -> fi) and full-width forms that would otherwise
    # embed and keyword-match differently from their plain equivalents.
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # NFKC leaves NBSP alone; it reads as a space but doesn't match one.
    text = text.replace("\u00a0", " ")
    text = _LINEBREAK_HYPHEN.sub(r"\1\2", text)
    text = _MANY_SPACES.sub(" ", text)
    text = _TRAILING_SPACE.sub("", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()
