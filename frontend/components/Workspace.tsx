"use client";

import { SlidersHorizontal, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchCatalog } from "@/lib/api";
import type { Catalog, Mode, QueryFilters } from "@/lib/types";
import { useAnalysis } from "@/lib/useAnalysis";
import { useMatter } from "@/lib/useMatter";
import { useResearch } from "@/lib/useResearch";
import { AnswerView } from "./AnswerView";
import { AuthorityList } from "./AuthorityList";
import { CaseAnalysisView } from "./CaseAnalysisView";
import { EmptyState } from "./EmptyState";
import { FilterRail } from "./FilterRail";
import { Header } from "./Header";
import { MatterRail } from "./MatterRail";
import { PlanStrip } from "./PlanStrip";
import { QueryComposer } from "./QueryComposer";
import { SourcePanel } from "./SourcePanel";

const NO_FILTERS: QueryFilters = { collections: [], courts: [], year_from: null, year_to: null };

/**
 * The research desk: filter rail, working page, bundle. Owns the little state
 * that crosses components - filters, mode, which authority is open - and
 * hands everything else to the research hook.
 */
export function Workspace() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [filters, setFilters] = useState<QueryFilters>(NO_FILTERS);
  const [mode, setMode] = useState<Mode>("ask");
  const [question, setQuestion] = useState("");
  const [railOpen, setRailOpen] = useState(false);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const chips = useRef(new Map<number, HTMLButtonElement>());
  const lastOpener = useRef<HTMLButtonElement | null>(null);
  const { state, submit, cancel } = useResearch();
  const matter = useMatter();
  const current = matter.current;
  const matterId = current?.id ?? null;
  const analysis = useAnalysis();
  const { start: startAnalysis, show: showAnalysis } = analysis;
  const refreshMatter = matter.refresh;
  // The page shows a query's result or the matter's working file, never both.
  const [view, setView] = useState<"desk" | "analysis">("desk");

  useEffect(() => {
    fetchCatalog().then(setCatalog).catch((e: Error) => setCatalogError(e.message));
  }, []);

  const courtNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const collection of catalog?.collections ?? []) {
      for (const court of collection.courts) names.set(court.code, court.name);
    }
    return names;
  }, [catalog]);

  const busy = state.phase !== "idle" && state.phase !== "done";

  // A new query replaces the bundle's contents; an open tab pointing at the
  // previous query's authorities would be a lie.
  const ask = useCallback(
    (text: string) => {
      setOpenIndex(null);
      setView("desk");
      submit(text, mode, filters, matterId);
    },
    [submit, mode, filters, matterId],
  );

  const analyse = useCallback(() => {
    if (!matterId) return;
    setOpenIndex(null);
    setView("analysis");
    startAnalysis(matterId).then(refreshMatter);
  }, [matterId, startAnalysis, refreshMatter]);

  const stored = current?.analysis ?? null;
  const openAnalysis = useCallback(() => {
    if (!stored) return;
    setOpenIndex(null);
    setView("analysis");
    showAnalysis(stored);
  }, [stored, showAnalysis]);

  // A research question from the working file goes straight to the desk.
  const research = useCallback(
    (text: string) => {
      setMode("research");
      setQuestion(text);
      setOpenIndex(null);
      setView("desk");
      submit(text, "research", filters, matterId);
    },
    [submit, filters, matterId],
  );

  const registerChip = useCallback((index: number, el: HTMLButtonElement | null) => {
    if (el) chips.current.set(index, el);
    else chips.current.delete(index);
  }, []);

  const openAuthority = useCallback((index: number) => {
    lastOpener.current = chips.current.get(index) ?? null;
    setOpenIndex(index);
  }, []);

  const closeAuthority = useCallback(() => {
    setOpenIndex(null);
    lastOpener.current?.focus();
  }, []);

  useEffect(() => {
    if (!railOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setRailOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [railOpen]);

  // What the bundle opens onto: a query's citations, or the working file's passages.
  const citations = view === "analysis" ? (analysis.state.analysis?.sources ?? []) : state.citations;
  const bundleOpen = openIndex !== null && citations.some((c) => c.index === openIndex);

  return (
    <div className="flex min-h-dvh flex-col">
      <Header>
        <button
          type="button"
          onClick={() => setRailOpen(true)}
          className="inline-flex min-h-9 items-center gap-2 rounded-control border border-rule-2 px-3 text-sm text-ink-2 hover:text-ink lg:hidden"
          aria-expanded={railOpen}
          aria-controls="filter-rail"
        >
          <SlidersHorizontal size={15} aria-hidden="true" />
          Filters
        </button>
      </Header>

      {/*
        Three columns need real width. Below lg the rail is a sheet and the
        bundle a bottom sheet; from lg the rail is a column and the bundle a
        drawer over the page; from xl all three sit side by side.
      */}
      <div
        className={[
          "grid flex-1 lg:grid-cols-[260px_minmax(0,1fr)]",
          bundleOpen ? "xl:grid-cols-[260px_minmax(0,1fr)_minmax(360px,420px)]" : "",
        ].join(" ")}
      >
        {/* Filter rail: a column on desktop, a sheet from the left on smaller screens. */}
        <aside
          id="filter-rail"
          className={[
            "bg-paper-2 lg:static lg:block lg:border-r lg:border-rule",
            railOpen
              ? "fixed inset-y-0 left-0 z-40 w-[min(320px,88vw)] overflow-y-auto border-r border-rule-2 shadow-drawer"
              : "hidden",
          ].join(" ")}
        >
          <div className="flex items-center justify-between px-5 pt-4 lg:pt-6">
            <h2 className="font-mono text-xs uppercase tracking-[0.08em] text-ink-3">Matter</h2>
            <button
              type="button"
              onClick={() => setRailOpen(false)}
              aria-label="Close filters"
              className="grid size-9 place-items-center rounded-control text-ink-2 hover:bg-paper hover:text-ink lg:hidden"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          <div className="px-5 pt-3">
            <MatterRail
              matters={matter.matters}
              current={matter.current}
              error={matter.error}
              onSelect={matter.select}
              onCreate={matter.create}
              onUpload={matter.upload}
              onRemove={matter.remove}
              analysing={analysis.state.phase === "running"}
              onAnalyse={analyse}
              onOpenAnalysis={openAnalysis}
            />
          </div>
          <h2 className="px-5 pt-8 font-mono text-xs uppercase tracking-[0.08em] text-ink-3">
            Restrict to
          </h2>
          <div className="px-5 pt-4 pb-8">
            {catalogError ? (
              <p className="text-sm text-ink-2">Filters unavailable: {catalogError}</p>
            ) : (
              <FilterRail
                catalog={catalog}
                value={filters}
                onChange={setFilters}
                matter={matter.current}
              />
            )}
          </div>
        </aside>
        {railOpen && (
          <button
            type="button"
            aria-label="Close filters"
            onClick={() => setRailOpen(false)}
            className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          />
        )}

        <main className="min-w-0 px-4 pt-5 pb-28 md:px-8 lg:px-10 lg:pb-16">
          <div className="mx-auto max-w-[76ch]">
            <QueryComposer
              value={question}
              onChange={setQuestion}
              mode={mode}
              onModeChange={setMode}
              busy={busy}
              onSubmit={ask}
              onCancel={cancel}
            />

            <div className="mt-3">
              <PlanStrip
                phase={state.phase}
                mode={state.mode}
                plan={state.plan}
                retrieval={state.retrieval}
                reviews={state.reviews}
                courtNames={courtNames}
                grounded={state.result?.grounded}
              />
            </div>

            <div className="mt-6">
              {view === "analysis" && matter.current ? (
                <CaseAnalysisView
                  matterName={matter.current.name}
                  state={analysis.state}
                  activeIndex={bundleOpen ? openIndex : null}
                  onOpen={openAuthority}
                  registerChip={registerChip}
                  onResearch={research}
                />
              ) : state.error ? (
                <p className="max-w-[60ch] border-l border-rule-2 pl-4 text-ink-2">
                  The query failed: {state.error}. Try again in a moment.
                </p>
              ) : state.phase === "idle" ? (
                <EmptyState
                  mode={mode}
                  catalog={catalog}
                  onPick={(q) => {
                    setQuestion(q);
                    ask(q);
                  }}
                />
              ) : state.mode !== "search" ? (
                <AnswerView
                  phase={state.phase}
                  draft={state.draft}
                  result={state.result}
                  citations={state.citations}
                  activeIndex={bundleOpen ? openIndex : null}
                  onOpen={openAuthority}
                  registerChip={registerChip}
                />
              ) : state.citations.length ? (
                <AuthorityList
                  citations={state.citations}
                  activeIndex={bundleOpen ? openIndex : null}
                  onOpen={openAuthority}
                  registerChip={registerChip}
                  showPassage
                  heading={`${state.citations.length} passages`}
                />
              ) : state.phase === "done" ? (
                <p className="max-w-[60ch] text-ink-2">
                  Nothing relevant enough was found. Try naming the Act, the court, or the parties.
                </p>
              ) : (
                <SearchSkeleton />
              )}
            </div>
          </div>
        </main>

        {bundleOpen && openIndex !== null && (
          <SourcePanel
            citations={citations}
            index={openIndex}
            onNavigate={setOpenIndex}
            onClose={closeAuthority}
          />
        )}
      </div>
    </div>
  );
}

function SearchSkeleton() {
  return (
    <div className="divide-y divide-rule border-y border-rule" aria-hidden="true">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="grid grid-cols-[2rem_1fr] gap-x-3 py-3">
          <div className="skeleton h-3.5 w-4" />
          <div className="space-y-2">
            <div className="skeleton h-4 w-[70%]" />
            <div className="skeleton h-3 w-[40%]" />
            <div className="skeleton h-3.5 w-[95%]" />
            <div className="skeleton h-3.5 w-[85%]" />
          </div>
        </div>
      ))}
    </div>
  );
}
