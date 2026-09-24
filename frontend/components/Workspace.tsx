"use client";

import { PanelLeft, SquarePen } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchCatalog } from "@/lib/api";
import type { Catalog, Mode, QueryFilters } from "@/lib/types";
import { type Conversation, useHistory, useSidebarFold } from "@/lib/history";
import { useAnalysis } from "@/lib/useAnalysis";
import { useMatter } from "@/lib/useMatter";
import { type ResearchState, useResearch } from "@/lib/useResearch";
import { AnswerView } from "./AnswerView";
import { AuthorityList } from "./AuthorityList";
import { CaseAnalysisView } from "./CaseAnalysisView";
import { EmptyState } from "./EmptyState";
import { FilterRail } from "./FilterRail";
import { Header } from "./Header";
import { HistoryList } from "./HistoryList";
import { MatterRail } from "./MatterRail";
import { PlanStrip } from "./PlanStrip";
import { QueryComposer } from "./QueryComposer";
import { Sidebar, SidebarSection } from "./Sidebar";
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
  const matter = useMatter();
  const current = matter.current;
  const matterId = current?.id ?? null;
  const analysis = useAnalysis();
  const history = useHistory();
  const [collapsed, foldSidebar] = useSidebarFold();
  const { save: saveConversation } = history;
  const [openConversation, setOpenConversation] = useState<string | null>(null);

  // What a finished run should be filed under, decided when it starts: a
  // reopened conversation is already in the list, and an errored one is not
  // worth a place in it.
  const filing = useRef<{ matterId: string | null; reopened: boolean }>({
    matterId: null,
    reopened: false,
  });
  const onFinished = useCallback(
    (finished: ResearchState) => {
      if (finished.error || filing.current.reopened) return;
      setOpenConversation(saveConversation(finished.question, finished, filing.current.matterId));
    },
    [saveConversation],
  );
  const { state, submit, cancel, restore, reset } = useResearch(onFinished);
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

  const toggleSidebar = useCallback(() => {
    // Below lg the column is a sheet, and the same control opens it.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      setRailOpen((wasOpen) => !wasOpen);
      return;
    }
    foldSidebar();
  }, [foldSidebar]);

  // A new query replaces the bundle's contents; an open tab pointing at the
  // previous query's authorities would be a lie.
  const ask = useCallback(
    (text: string) => {
      setOpenIndex(null);
      setView("desk");
      setOpenConversation(null);
      filing.current = { matterId, reopened: false };
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

  const newQuestion = useCallback(() => {
    reset();
    setQuestion("");
    setOpenIndex(null);
    setView("desk");
    setOpenConversation(null);
    filing.current = { matterId, reopened: false };
    setRailOpen(false);
  }, [reset, matterId]);

  const openConversationAt = useCallback(
    (conversation: Conversation) => {
      restore(conversation.state);
      setQuestion(conversation.state.question);
      setMode(conversation.state.mode);
      setOpenIndex(null);
      setView("desk");
      setOpenConversation(conversation.id);
      filing.current = { matterId, reopened: true };
      setRailOpen(false);
    },
    [restore, matterId],
  );

  const forgetConversation = useCallback(
    (id: string) => {
      history.remove(id);
      if (id === openConversation) newQuestion();
    },
    [history, openConversation, newQuestion],
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
  // Whether there is anything to read yet: what moves the composer down.
  const started = view === "analysis" || state.phase !== "idle";

  const body =
    view === "analysis" && matter.current ? (
      <CaseAnalysisView
        matterName={matter.current.name}
        state={analysis.state}
        activeIndex={bundleOpen ? openIndex : null}
        onOpen={openAuthority}
        registerChip={registerChip}
        onResearch={research}
      />
    ) : state.error ? (
      <p className="max-w-[60ch] text-ink-2">{state.error}</p>
    ) : state.phase === "idle" ? (
      <EmptyState
        mode={mode}
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
    );

  return (
    <div className="min-h-dvh">
      <Header>
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? "Show the sidebar" : "Hide the sidebar"}
          aria-expanded={!collapsed}
          aria-controls="sidebar"
          className="press grid size-9 place-items-center rounded-control text-ink-2 transition-colors duration-150 hover:bg-paper-2 hover:text-ink"
        >
          <PanelLeft size={17} aria-hidden="true" />
        </button>
      </Header>

      <Sidebar collapsed={collapsed} open={railOpen} onClose={() => setRailOpen(false)}>
        <button
          type="button"
          onClick={newQuestion}
          className="lift inline-flex min-h-9 items-center gap-2 self-start rounded-control border border-rule-2 px-3 text-sm text-ink transition-colors hover:border-ink-3"
        >
          <SquarePen size={15} aria-hidden="true" />
          New question
        </button>

        <SidebarSection title="History">
          <HistoryList
            conversations={history.conversations}
            currentId={openConversation}
            onOpen={openConversationAt}
            onRemove={forgetConversation}
          />
        </SidebarSection>

        <SidebarSection title="Matter">
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
        </SidebarSection>

        <SidebarSection title="Restrict to">
          {catalogError ? (
            <p className="px-2 text-sm text-ink-3">{catalogError}</p>
          ) : (
            <FilterRail
              catalog={catalog}
              value={filters}
              onChange={setFilters}
              matter={matter.current}
            />
          )}
        </SidebarSection>
      </Sidebar>

      {/*
        The page reserves the column's width rather than the column pushing
        it: the fold is then one transform on the sidebar and one margin on
        the page, and the bundle keeps its own place at the right.
      */}
      <div
        className={[
          "flex min-h-[calc(100dvh-3.5rem)] transition-[margin] duration-300 ease-out-expo motion-reduce:transition-none",
          collapsed ? "lg:ml-0" : "lg:ml-[280px]",
        ].join(" ")}
      >
        <main
          className={[
            "flex min-w-0 flex-1 flex-col px-4 md:px-8 lg:px-10",
            started ? "pb-4 pt-5" : "justify-center pb-16 pt-5",
          ].join(" ")}
        >
          {started ? (
            <>
              <div className="mx-auto w-full max-w-[76ch] flex-1">
                <PlanStrip
                  phase={state.phase}
                  mode={state.mode}
                  plan={state.plan}
                  retrieval={state.retrieval}
                  reviews={state.reviews}
                  courtNames={courtNames}
                  grounded={state.result?.grounded}
                />
                <div className="mt-4">{body}</div>
              </div>
              <div className="sticky bottom-0 mx-auto mt-6 w-full max-w-[76ch] bg-paper pb-4 pt-2">
                <QueryComposer
                  value={question}
                  onChange={setQuestion}
                  mode={mode}
                  onModeChange={setMode}
                  busy={busy}
                  onSubmit={ask}
                  onCancel={cancel}
                />
              </div>
            </>
          ) : (
            <div className="mx-auto w-full max-w-[76ch]">
              <QueryComposer
                value={question}
                onChange={setQuestion}
                mode={mode}
                onModeChange={setMode}
                busy={busy}
                onSubmit={ask}
                onCancel={cancel}
              />
              <div className="mt-5">{body}</div>
            </div>
          )}
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
