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


def window(children: list[str], index: int, radius: int) -> str:
    """The parent window around one child: itself plus `radius` neighbours each side.

    Clamped at the ends rather than wrapped, so the first child's window simply
    reaches further forward than back.
    """
    start = max(0, index - radius)
    return "\n\n".join(children[start : index + radius + 1])


def attach_parents(children: list[str], radius: int) -> list[Parented]:
    """Pair every child with its surrounding window.

    Grouping is the caller's job: children must already be in reading order and
    must not span a boundary the window shouldn't cross (a PDF page, a source
    document). Passing unrelated children in one list would build windows that
    straddle documents.
    """
    return [Parented(text=child, parent_text=window(children, i, radius)) for i, child in enumerate(children)]
