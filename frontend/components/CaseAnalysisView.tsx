"use client";

import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { formatDate } from "@/lib/format";
import type { AnalysisState } from "@/lib/useAnalysis";
import type { Authority } from "@/lib/types";
import { AuthorityList } from "./AuthorityList";
import { CitationChip } from "./CitationChip";
import { Prose } from "./Prose";

interface Props {
  matterName: string;
  state: AnalysisState;
  activeIndex: number | null;
  onOpen: (index: number) => void;
  registerChip: (index: number, el: HTMLButtonElement | null) => void;
  onResearch: (question: string) => void;
}

const STEP_LINE: Record<string, string> = {
  documents: "Reading the documents…",
  authorities: "Finding the law they cite…",
  extract: "Reading each document for parties, facts and dates…",
  chronology: "Putting the events in order…",
  synthesis: "Weighing the issues and the conflicts…",
  report: "Writing the report…",
};

/**
 * The matter's working file: what its documents say, section by section,
 * each item a tab into the passage it was read from. Sections appear as
 * their step lands; a step that could not run says so in its own words.
 */
export function CaseAnalysisView({ matterName, state, activeIndex, onOpen, registerChip, onResearch }: Props) {
  const { analysis, steps, phase, error } = state;
  if (!analysis) return null;
  const sources = analysis.sources.length;
  const running = Object.entries(steps).find(([, status]) => status === "started" || status === "progress")?.[0];

  const chip = (index: number | null, key: string) =>
    index === null ? null : (
      <CitationChip
        key={key}
        ref={(el) => registerChip(index, el)}
        index={index}
        exists={index >= 1 && index <= sources}
        active={activeIndex === index}
        onOpen={onOpen}
      />
    );
  const chips = (indices: number[], key: string) => indices.map((i, n) => chip(i, `${key}-${n}`));

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-mono text-xs uppercase tracking-[0.08em] text-ink-3">Case analysis</h2>
        <span className="font-serif text-base text-ink">{matterName}</span>
        {phase === "running" && running && (
          <span className="font-mono text-xs text-red" role="status" aria-live="polite">
            {STEP_LINE[running] ?? running}
          </span>
        )}
      </div>

      {error && <p className="mt-4 max-w-[60ch] border-l border-rule-2 pl-4 text-ink-2">{error}</p>}

      <Section title="Parties" count={analysis.parties.length} pending={steps.extract === "started" || steps.extract === "progress"}>
        {analysis.parties.map((party, i) => (
          <Row key={i} primary={party.name} secondary={party.role} tail={chip(party.source, `party-${i}`)} />
        ))}
      </Section>

      <Section title="Chronology" count={analysis.chronology.length} pending={steps.chronology === "started"}>
        {analysis.chronology.map((event, i) => (
          <Row
            key={i}
            lead={event.date ? formatDate(event.date) ?? event.when : event.when}
            primary={event.description}
            tail={chip(event.source, `event-${i}`)}
          />
        ))}
      </Section>

      <Section title="Authorities cited" count={analysis.authorities.length} pending={steps.authorities === "started"}>
        {analysis.authorities.map((authority, i) => (
          <AuthorityRow key={i} authority={authority} tail={chips(authority.sources, `auth-${i}`)} />
        ))}
      </Section>

      <Section title="Issues" count={analysis.issues.length} pending={steps.synthesis === "started"}>
        {analysis.issues.map((issue, i) => (
          <Row key={i} primary={issue.question} tail={chips(issue.sources, `issue-${i}`)} />
        ))}
      </Section>

      <Section title="Contradictions" count={analysis.contradictions.length} pending={steps.synthesis === "started"}>
        {analysis.contradictions.map((c, i) => (
          <li key={i} className="py-3">
            <p className="font-serif text-base leading-snug text-ink">{c.point}</p>
            <p className="mt-1.5 font-serif text-[0.95rem] leading-relaxed text-ink-2">
              “{c.first}” <span className="font-mono text-xs text-ink-3">against</span> “{c.second}”{" "}
              {chips(c.sources, `contra-${i}`)}
            </p>
          </li>
        ))}
      </Section>

      <Section title="Research questions" count={analysis.research_questions.length} pending={steps.synthesis === "started"}>
        {analysis.research_questions.map((q, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => onResearch(q.question)}
              className="group block w-full py-3 text-left transition-colors duration-150 hover:bg-sheet"
            >
              <span className="block font-serif text-base leading-snug text-ink group-hover:text-red">{q.question}</span>
              <span className="mt-0.5 block font-mono text-xs text-ink-3">{q.why}</span>
            </button>
          </li>
        ))}
      </Section>

      {(analysis.report || steps.report === "started") && (
        <section className="mt-8">
          <h3 className="mb-3 font-mono text-xs uppercase tracking-[0.08em] text-ink-3">Report</h3>
          {analysis.report ? (
            <Prose text={analysis.report} sourceCount={sources} activeIndex={activeIndex} onOpen={onOpen} registerChip={registerChip} />
          ) : (
            <div className="space-y-3" aria-hidden="true">
              <div className="skeleton h-4 w-[92%]" />
              <div className="skeleton h-4 w-[70%]" />
            </div>
          )}
        </section>
      )}

      {analysis.warnings.length > 0 && phase === "done" && (
        <ul className="mt-8 space-y-1 font-mono text-xs text-ink-3">
          {analysis.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {analysis.sources.length > 0 && (
        <AuthorityList citations={analysis.sources} activeIndex={activeIndex} onOpen={onOpen} registerChip={registerChip} heading="Passages" />
      )}
    </div>
  );
}

function Section({ title, count, pending, children }: { title: string; count: number; pending: boolean; children: ReactNode }) {
  if (!count && !pending) return null;
  return (
    <section className="mt-8" aria-label={title}>
      <h3 className="mb-2 font-mono text-xs uppercase tracking-[0.08em] text-ink-3">
        {title} {count > 0 && <span className="tabular">· {count}</span>}
      </h3>
      {count > 0 ? (
        <ul className="divide-y divide-rule border-y border-rule">{children}</ul>
      ) : (
        <div className="space-y-2 py-2" aria-hidden="true">
          <div className="skeleton h-3.5 w-[60%]" />
          <div className="skeleton h-3.5 w-[45%]" />
        </div>
      )}
    </section>
  );
}

function Row({ lead, primary, secondary, tail }: { lead?: string; primary: string; secondary?: string; tail?: ReactNode }) {
  return (
    <li className="flex items-baseline gap-3 py-2.5">
      {lead && <span className="w-24 shrink-0 font-mono text-xs text-ink-3 tabular">{lead}</span>}
      <span className="min-w-0 flex-1">
        <span className="font-serif text-base leading-snug text-ink">{primary}</span>
        {secondary && <span className="ml-2 font-mono text-xs text-ink-3">{secondary}</span>}
      </span>
      {tail && <span className="shrink-0">{tail}</span>}
    </li>
  );
}

function AuthorityRow({ authority, tail }: { authority: Authority; tail: ReactNode }) {
  const detail = [
    authority.title && authority.title !== authority.ref ? authority.title : null,
    authority.applied_by ? `applied by ${authority.applied_by} ${authority.applied_by === 1 ? "judgment" : "judgments"}` : null,
  ].filter(Boolean);
  return (
    <li className="flex items-baseline gap-3 py-2.5">
      <span className="min-w-0 flex-1">
        {authority.url ? (
          <a
            href={authority.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-baseline gap-1.5 font-serif text-base leading-snug text-ink underline-offset-2 hover:text-red hover:underline"
          >
            {authority.ref}
            <ExternalLink size={12} aria-hidden="true" className="translate-y-px text-ink-3" />
          </a>
        ) : (
          <span className="font-serif text-base leading-snug text-ink">{authority.ref}</span>
        )}
        {detail.length > 0 && <span className="mt-0.5 block font-mono text-xs text-ink-3">{detail.join(" · ")}</span>}
      </span>
      <span className="shrink-0">{tail}</span>
    </li>
  );
}
