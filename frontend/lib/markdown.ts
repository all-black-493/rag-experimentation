/**
 * The small subset of markdown the prompts actually produce: paragraphs,
 * bullet and numbered lists, **bold**, *em*, and - for a memo - headings.
 * Rendered to a block structure the answer view turns into elements - never
 * into HTML strings, so there is nothing to sanitise.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "em"; text: string };

export type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; inlines: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
// The memo prompt asks for headings (Issue, Law, …); the answer prompt asks for none.
const HEADING = /^\s*#{1,6}\s+(.*)$/;
// **strong** and *em* - the latter is how the model sets case names, which is
// also how a law report sets them.
const EMPHASIS = /\*\*(.+?)\*\*|\*([^*\n]+?)\*/g;

export function inlines(text: string): Inline[] {
  const parts: Inline[] = [];
  let last = 0;
  for (const match of text.matchAll(EMPHASIS)) {
    if (match.index! > last) parts.push({ kind: "text", text: text.slice(last, match.index) });
    if (match[1] !== undefined) parts.push({ kind: "strong", text: match[1] });
    else parts.push({ kind: "em", text: match[2] });
    last = match.index! + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

export function blocks(markdown: string): Block[] {
  const out: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) out.push({ kind: "paragraph", inlines: inlines(paragraph.join(" ")) });
    paragraph = [];
  };
  const flushList = () => {
    if (list) out.push({ kind: "list", ordered: list.ordered, items: list.items.map(inlines) });
    list = null;
  };

  for (const line of markdown.split("\n")) {
    const heading = HEADING.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      out.push({ kind: "heading", text: heading[1].replace(/\*\*/g, "").trim() });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ?? numbered)![1]);
    } else if (!line.trim()) {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return out;
}
