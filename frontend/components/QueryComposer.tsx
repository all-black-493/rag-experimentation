"use client";

import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Mode } from "@/lib/types";
import { ModeToggle } from "./ModeToggle";

interface Props {
  value: string;
  onChange: (value: string) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  busy: boolean;
  onSubmit: (question: string) => void;
  onCancel: () => void;
}

/**
 * The query slip. Sits at the top of the working page, not the bottom: this
 * is a research desk, and the question is what the page is about.
 */
export function QueryComposer({ value, onChange, mode, onModeChange, busy, onSubmit, onCancel }: Props) {
  const question = value;
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Grow with the question, up to a few lines; the page scrolls after that.
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [question]);

  const submit = () => {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    onSubmit(trimmed);
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="rounded-panel border border-rule-2 bg-sheet"
    >
      <label htmlFor="question" className="sr-only">
        Your question
      </label>
      <textarea
        ref={textarea}
        id="question"
        name="question"
        rows={2}
        value={question}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder={
          mode === "ask"
            ? "What does the Employment Act say about severance pay?"
            : "Find passages on robbery with violence under section 296(2)"
        }
        className="block w-full resize-none bg-transparent px-4 pt-4 pb-2 font-serif text-read leading-relaxed placeholder:text-ink-3 focus:outline-none"
      />
      <div className="flex items-center justify-between gap-3 px-3 pb-3">
        <ModeToggle value={mode} onChange={onModeChange} />
        {busy ? (
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex min-h-9 items-center gap-2 rounded-control border border-rule-2 px-3 text-sm font-medium text-ink-2 transition-colors duration-150 hover:border-ink-3 hover:text-ink"
          >
            <Square size={14} strokeWidth={2} aria-hidden="true" />
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!question.trim()}
            className="inline-flex min-h-9 items-center gap-2 rounded-control bg-red px-3.5 text-sm font-medium text-sheet transition-colors duration-150 hover:bg-red-2 disabled:cursor-not-allowed disabled:bg-rule-2 disabled:text-ink-3"
          >
            {mode === "ask" ? "Ask" : "Search"}
            <ArrowUp size={15} strokeWidth={2.25} aria-hidden="true" />
          </button>
        )}
      </div>
    </form>
  );
}
