"use client";

import { Fragment, type ReactNode } from "react";
import { splitMarkers } from "@/lib/format";
import { blocks, type Inline } from "@/lib/markdown";
import { CitationChip } from "./CitationChip";

interface Props {
  text: string;
  // How many sources there are: a marker past the last renders inert.
  sourceCount: number;
  activeIndex: number | null;
  onOpen: (index: number) => void;
  registerChip?: (index: number, el: HTMLButtonElement | null) => void;
  streaming?: boolean;
}

/**
 * Model-written text as the desk sets it: paragraphs, lists, memo headings
 * as section labels, and every [n] as the tab of the authority it points to.
 */
export function Prose({ text, sourceCount, activeIndex, onOpen, registerChip, streaming = false }: Props) {
  const renderInline = (inline: Inline, key: number): ReactNode => {
    const parts = splitMarkers(inline.text).map((part, i) =>
      "marker" in part ? (
        <CitationChip
          key={`${key}-${i}`}
          ref={registerChip ? (el) => registerChip(part.marker, el) : undefined}
          index={part.marker}
          exists={part.marker >= 1 && part.marker <= sourceCount}
          active={activeIndex === part.marker}
          onOpen={onOpen}
        />
      ) : (
        <Fragment key={`${key}-${i}`}>{part.text}</Fragment>
      ),
    );
    if (inline.kind === "strong") return <strong key={key} className="font-semibold">{parts}</strong>;
    if (inline.kind === "em") return <em key={key}>{parts}</em>;
    return <Fragment key={key}>{parts}</Fragment>;
  };

  return (
    <div className="prose-law" aria-busy={streaming}>
      {blocks(text).map((block, i) =>
        block.kind === "heading" ? (
          <h2 key={i} className="mt-7 mb-2 font-mono text-xs uppercase tracking-[0.08em] text-ink-3 first:mt-0">
            {block.text}
          </h2>
        ) : block.kind === "paragraph" ? (
          <p key={i}>{block.inlines.map(renderInline)}</p>
        ) : block.ordered ? (
          <ol key={i} className="mt-3 list-decimal space-y-1.5 pl-6 marker:font-mono marker:text-sm marker:text-ink-3">
            {block.items.map((item, j) => (
              <li key={j}>{item.map(renderInline)}</li>
            ))}
          </ol>
        ) : (
          <ul key={i} className="mt-3 list-disc space-y-1.5 pl-6 marker:text-ink-3">
            {block.items.map((item, j) => (
              <li key={j}>{item.map(renderInline)}</li>
            ))}
          </ul>
        ),
      )}
      {streaming && (
        <span className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.2em] bg-red motion-safe:animate-pulse" aria-hidden="true" />
      )}
    </div>
  );
}
