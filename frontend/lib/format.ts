import type { Citation, Collection, SubQueryOutcome } from "./types";

export const COLLECTION_LABEL: Record<Collection, string> = {
  legislation: "Legislation",
  case_law: "Case law",
  matter: "Matter",
};

const DATE = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", year: "numeric" });

export function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? iso : DATE.format(date);
}

/** "Court of Appeal · 25 Mar 2026", "Act of 1953", or "p. 2" for the user's own document. */
export function provenance(citation: Citation): string {
  if (citation.collection === "case_law") {
    return [citation.court, formatDate(citation.decision_date)].filter(Boolean).join(" · ");
  }
  if (citation.collection === "matter") {
    return citation.page ? `p. ${citation.page}` : "";
  }
  return citation.year ? `Act of ${citation.year}` : "Legislation";
}

/** The one mono line under a title: "Case law · High Court · 24 Mar 2026". */
export function sourceLine(citation: Citation): string {
  return [COLLECTION_LABEL[citation.collection], provenance(citation)].filter(Boolean).join(" · ");
}

/** Where the citation opens: Kenya Law for the corpus, the stored original for a matter. */
export function openUrl(citation: Citation): string {
  return citation.collection === "matter" ? `/api${citation.url}` : citation.url;
}

/** A short line on what a sub-query covered: "Case law · Supreme Court · 2024–2026". */
export function describeOutcome(
  outcome: SubQueryOutcome,
  courtNames: Map<string, string>,
): string {
  const parts = [COLLECTION_LABEL[outcome.collection]];
  const courts = outcome.filters.courts?.map((code) => courtNames.get(code) ?? code.toUpperCase());
  if (courts?.length) parts.push(courts.join(", "));
  const { year_from, year_to } = outcome.filters;
  if (year_from && year_to) parts.push(year_from === year_to ? `${year_from}` : `${year_from}–${year_to}`);
  else if (year_from) parts.push(`from ${year_from}`);
  else if (year_to) parts.push(`to ${year_to}`);
  return parts.join(" · ");
}

/**
 * Split an answer into text and [n] markers so the markers can be rendered as
 * controls. At most three digits: "[2010]" in a neutral citation is a year,
 * not a reference (mirrors backend/app/scoring.py).
 */
export function splitMarkers(text: string): Array<{ text: string } | { marker: number }> {
  const parts: Array<{ text: string } | { marker: number }> = [];
  const pattern = /\[(\d{1,3})\]/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index! > last) parts.push({ text: text.slice(last, match.index) });
    parts.push({ marker: Number(match[1]) });
    last = match.index! + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}
