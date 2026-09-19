"""Render the matter fixtures (eval/fixtures/matter/*.md) as PDFs.

    uv run python eval/build_matter_fixtures.py

One matter, three documents a lawyer would actually hold - a lease, a demand
letter, a witness statement - authored as Markdown so they can be reviewed as
text, and rendered here so the eval exercises the PDF path: pages, boxes,
the viewer. The PDFs are committed; this script only needs re-running when
the Markdown changes. (MuPDF writes a fresh document id each time, so the
bytes differ per run; the eval keys documents by name, not by hash.)
"""

import html
import re
from pathlib import Path

import pymupdf

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "matter"

_CSS = """
body { font-family: serif; font-size: 10.5pt; line-height: 1.45; }
h1 { font-size: 13pt; margin: 0 0 6pt 0; }
h2 { font-size: 11pt; margin: 12pt 0 4pt 0; }
p { margin: 0 0 7pt 0; }
"""


def to_html(markdown: str) -> str:
    """Just headings and paragraphs: the fixtures use nothing else."""
    parts = []
    for block in re.split(r"\n\s*\n", markdown.strip()):
        lines = block.strip().splitlines()
        if all(line.startswith("# ") for line in lines):
            parts.extend(f"<h1>{html.escape(line[2:])}</h1>" for line in lines)
        elif len(lines) == 1 and lines[0].startswith("## "):
            parts.append(f"<h2>{html.escape(lines[0][3:])}</h2>")
        else:
            parts.append(f"<p>{html.escape(' '.join(lines))}</p>")
    return "".join(parts)


def render(source: Path) -> Path:
    target = source.with_suffix(".pdf")
    story = pymupdf.Story(html=to_html(source.read_text()), user_css=_CSS)
    writer = pymupdf.DocumentWriter(str(target))
    page_rect = pymupdf.paper_rect("a4")
    box = page_rect + (54, 54, -54, -54)
    more = True
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(box)
        story.draw(device)
        writer.end_page()
    writer.close()
    return target


def main() -> int:
    for source in sorted(FIXTURES.glob("*.md")):
        target = render(source)
        with pymupdf.open(str(target)) as doc:
            print(f"{target.name}: {len(doc)} pages, {target.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
