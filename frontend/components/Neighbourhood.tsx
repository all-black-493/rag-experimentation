"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { useNeighbourhood } from "@/lib/useNeighbourhood";
import type { GraphLink } from "@/lib/types";

const FOLD_AT = 20;

/**
 * What an authority cites and what cites it, from the citation graph.
 * Rows on hairlines like the bundle's index; a row whose document is in the
 * corpus opens it on kenyalaw.org. Nothing is rendered until the graph
 * answers, and nothing at all when it has no record of the document.
 */
export function Neighbourhood({ docId }: { docId: string }) {
  const neighbourhood = useNeighbourhood(docId);
  if (!neighbourhood) return null;
  return (
    <div className="mt-8 space-y-8">
      <LinkList heading="Cites" links={neighbourhood.cites} direction="out" />
      <LinkList heading="Cited by" links={neighbourhood.cited_by} direction="in" />
    </div>
  );
}

function LinkList({
  heading,
  links,
  direction,
}: {
  heading: string;
  links: GraphLink[];
  direction: "out" | "in";
}) {
  const [unfolded, setUnfolded] = useState(false);
  if (links.length === 0) return null;
  const shown = unfolded ? links : links.slice(0, FOLD_AT);
  const hidden = links.length - shown.length;
  return (
    <section aria-label={heading}>
      <h3 className="mb-2 font-mono text-xs uppercase tracking-[0.08em] text-ink-3">
        {heading} · <span className="tabular">{links.length}</span>
      </h3>
      <ul className="divide-y divide-rule border-y border-rule">
        {shown.map((link) => (
          <li key={link.doc_id ?? link.refs[0]}>
            <Row link={link} direction={direction} />
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setUnfolded(true)}
          className="mt-1 py-2 font-mono text-xs text-red underline-offset-2 hover:underline"
        >
          <span className="tabular">{hidden}</span> more
        </button>
      )}
    </section>
  );
}

function Row({ link, direction }: { link: GraphLink; direction: "out" | "in" }) {
  const { primary, secondary } = describe(link, direction);
  const body = (
    <span className="min-w-0 flex-1">
      <span className="block font-serif text-[0.95rem] leading-snug text-ink">{primary}</span>
      {secondary && (
        <span className="mt-0.5 block font-mono text-xs text-ink-3">{secondary}</span>
      )}
    </span>
  );
  if (!link.url) return <div className="py-2.5">{body}</div>;
  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group -mx-2 flex items-start gap-3 rounded-control px-2 py-2.5 transition-colors duration-150 hover:bg-paper-2"
    >
      {body}
      <ExternalLink
        size={13}
        aria-hidden="true"
        className="mt-1 shrink-0 text-ink-3 transition-colors duration-150 group-hover:text-red"
      />
    </a>
  );
}

/**
 * The row's two lines. The document's title leads when the corpus has it;
 * otherwise the citation as written, with the parties when the passage named
 * them. Provisions lose their "of the … Act" tail: the title already says it.
 */
function describe(link: GraphLink, direction: "out" | "in"): { primary: string; secondary: string | null } {
  const provisions = link.kind === "applies" ? link.refs.map(shortProvision).join(" · ") : null;
  if (link.title) {
    return { primary: link.title, secondary: provisions };
  }
  // Only a target can be unresolved; the citing document is always indexed.
  const written = link.parties ? `${link.parties} ${link.refs[0]}` : link.refs[0];
  return {
    primary: written,
    secondary: direction === "out" && link.refs.length > 1 ? link.refs.slice(1).join(" · ") : null,
  };
}

function shortProvision(ref: string): string {
  return ref.replace(/\s+of\s+the\s+.*$/i, "");
}
