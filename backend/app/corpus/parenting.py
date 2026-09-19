"""Small-to-big: index precise children, generate from their parent window.

Two things pull chunk size in opposite directions. Retrieval wants small chunks:
a 650-token passage embeds to an average of everything in it, so a single
relevant sentence gets diluted by the paragraphs around it. Generation wants
large ones: a model handed an isolated sentence has no idea what "the limit"
refers to.

Small-to-big takes both. The embedded and matched unit is a small child; what
the model reads is the parent window that child sits in.

It also buys a precise highlight. A citation's bbox is the *child's* box - the
few lines that actually matched - instead of the union of everything in a large
chunk, which on a dense page approximates highlighting the whole page.

The parent text is denormalised onto each child rather than fetched at query
time. Storing it repeatedly costs disk; fetching it would cost one extra
Weaviate round trip per retrieved chunk, on the request path, every time.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Parented:
    """A child chunk plus the window a model should read it in."""

    text: str
    parent_text: str


# Consecutive children overlap by design (the splitter's chunk_overlap), so a
# window that simply concatenated them would repeat every seam - once for the
# reader in the source panel, once for the model in its context, which was
# enough to make it remark that passages were "cut off". Bounded so a
# pathological pair can't make the search quadratic.
_MAX_OVERLAP = 600
_MIN_OVERLAP = 20


def _overlap(text: str, part: str) -> int:
    """How many leading characters of `part` repeat the tail of `text`."""
    for k in range(min(len(text), len(part), _MAX_OVERLAP), _MIN_OVERLAP - 1, -1):
        if text.endswith(part[:k]):
            return k
    return 0


def join_children(parts: list[str]) -> str:
    """Concatenate neighbouring children without repeating their overlap.

    Every child remains a verbatim substring of the result - the overlap is
    dropped from the *front* of the later child, whose text is already there -
    so a highlight can still find the matched child inside its window.
    """
    if not parts:
        return ""
    text = parts[0]
    for part in parts[1:]:
        k = _overlap(text, part)
        text = text + part[k:] if k else f"{text}\n\n{part}"
    return text


def window(children: list[str], index: int, radius: int) -> str:
    """The parent window around one child: itself plus `radius` neighbours each side.

    Clamped at the ends rather than wrapped, so the first child's window simply
    reaches further forward than back.
    """
    start = max(0, index - radius)
    return join_children(children[start : index + radius + 1])


def attach_parents(children: list[str], radius: int) -> list[Parented]:
    """Pair every child with its surrounding window.

    Grouping is the caller's job: children must already be in reading order and
    must not span a boundary the window shouldn't cross (a PDF page, a source
    document). Passing unrelated children in one list would build windows that
    straddle documents.
    """
    return [Parented(text=child, parent_text=window(children, i, radius)) for i, child in enumerate(children)]
