"use client";

import { ChevronDown, Plus, X } from "lucide-react";
import { useRef, useState } from "react";
import type { Matter, MatterDocument } from "@/lib/types";

interface Props {
  matters: Matter[];
  current: Matter | null;
  error: string | null;
  onSelect: (id: string | null) => void;
  onCreate: (name: string) => Promise<unknown>;
  onUpload: (files: FileList) => void;
  onRemove: (docId: string) => void;
}

const ACCEPT = ".pdf,.docx,.txt,.md";

/**
 * The matter in use and its documents: a native select to change it, one row
 * per document with what the index knows about it, and the way to add more.
 * Everything shown is a fact about the matter; nothing explains itself.
 */
export function MatterRail({ matters, current, error, onSelect, onCreate, onUpload, onRemove }: Props) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const create = async () => {
    const trimmed = name.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      await onCreate(trimmed);
      setName("");
      setNaming(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="matter-select">
          Matter
        </label>
        <div className="relative min-w-0 flex-1">
          <select
            id="matter-select"
            value={current?.id ?? ""}
            onChange={(event) => onSelect(event.target.value || null)}
            className="w-full appearance-none truncate rounded-control border border-rule-2 bg-sheet py-1.5 pl-2.5 pr-8 text-sm text-ink focus:border-ink-3 focus:outline-none"
          >
            <option value="">No matter</option>
            {matters.map((matter) => (
              <option key={matter.id} value={matter.id}>
                {matter.name}
              </option>
            ))}
          </select>
          <ChevronDown
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-3"
          />
        </div>
        {!naming && (
          <button
            type="button"
            onClick={() => setNaming(true)}
            aria-label="New matter"
            className="grid size-9 shrink-0 place-items-center rounded-control border border-rule-2 text-ink-2 transition-colors duration-150 hover:border-ink-3 hover:text-ink"
          >
            <Plus size={15} aria-hidden="true" />
          </button>
        )}
      </div>

      {naming && (
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <label className="sr-only" htmlFor="matter-name">
            Matter name
          </label>
          <input
            id="matter-name"
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setNaming(false);
                setName("");
              }
            }}
            placeholder="Karanja v Otieno"
            maxLength={200}
            className="w-full min-w-0 rounded-control border border-rule-2 bg-sheet px-2.5 py-1.5 font-serif text-sm placeholder:text-ink-3 focus:border-ink-3 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!name.trim() || creating}
            className="shrink-0 rounded-control bg-red px-3 py-1.5 text-sm font-medium text-sheet transition-colors duration-150 hover:bg-red-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Create
          </button>
        </form>
      )}

      {current && (
        <>
          {current.documents.length > 0 && (
            <ul className="divide-y divide-rule border-y border-rule">
              {current.documents.map((document) => (
                <li key={document.doc_id} className="flex items-start gap-2 py-2">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-serif text-[0.95rem] leading-snug text-ink">
                      {document.name}
                    </span>
                    <DocumentLine document={document} />
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemove(document.doc_id)}
                    aria-label={`Remove ${document.name}`}
                    className="grid size-7 shrink-0 place-items-center rounded-control text-ink-3 transition-colors duration-150 hover:bg-paper hover:text-red"
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            multiple
            className="sr-only"
            onChange={(event) => {
              if (event.target.files?.length) onUpload(event.target.files);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="inline-flex min-h-9 items-center gap-2 self-start rounded-control border border-rule-2 px-3 text-sm text-ink-2 transition-colors duration-150 hover:border-ink-3 hover:text-ink"
          >
            <Plus size={15} aria-hidden="true" />
            Add documents
          </button>
        </>
      )}

      {error && <p className="text-xs text-red">{error}</p>}
    </div>
  );
}

/** What the index knows: type, pages, passages; or that it is still working, or why it failed. */
function DocumentLine({ document }: { document: MatterDocument }) {
  if (document.status === "failed") {
    return <span className="mt-0.5 block font-mono text-xs text-ink-3">{document.error ?? "failed"}</span>;
  }
  if (document.status !== "indexed") {
    return <span className="mt-0.5 block font-mono text-xs text-red">indexing</span>;
  }
  const parts = [
    document.profile?.document_type,
    document.pages !== null ? `${document.pages} ${document.pages === 1 ? "page" : "pages"}` : null,
    document.chunks !== null ? `${document.chunks} passages` : null,
  ].filter(Boolean);
  return <span className="mt-0.5 block font-mono text-xs text-ink-3">{parts.join(" · ")}</span>;
}
