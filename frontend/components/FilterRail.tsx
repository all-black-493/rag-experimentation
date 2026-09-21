"use client";

import type { Catalog, Collection, Matter, QueryFilters } from "@/lib/types";

interface Props {
  catalog: Catalog | null;
  value: QueryFilters;
  onChange: (filters: QueryFilters) => void;
  // The matter in use, if any: its documents are one more source to tick.
  matter?: Matter | null;
}

/**
 * The user's hard constraints. Built from the catalog, so it can never offer
 * a court or a year the corpus doesn't have. Nothing here is decorative: every
 * control changes what the planner is allowed to search.
 */
export function FilterRail({ catalog, value, onChange, matter = null }: Props) {
  if (!catalog) return <RailSkeleton />;

  const sources: { key: Collection; label: string; count: number }[] = [
    ...catalog.collections.map((c) => ({ key: c.key, label: c.label, count: c.documents })),
    ...(matter
      ? [
          {
            key: "matter" as const,
            label: matter.name,
            count: matter.documents.filter((d) => d.status === "indexed").length,
          },
        ]
      : []),
  ];

  const caseLaw = catalog.collections.find((c) => c.key === "case_law");
  const caseLawAllowed = value.collections.length === 0 || value.collections.includes("case_law");
  const years = catalog.collections
    .flatMap((c) => [c.year_min, c.year_max])
    .filter((y): y is number => y !== null);
  const yearMin = years.length ? Math.min(...years) : undefined;
  const yearMax = years.length ? Math.max(...years) : undefined;
  const isDefault =
    !value.collections.length && !value.courts.length && value.year_from === null && value.year_to === null;

  const toggleCollection = (key: Collection) => {
    const next = value.collections.includes(key)
      ? value.collections.filter((c) => c !== key)
      : [...value.collections, key];
    onChange({ ...value, collections: next, courts: next.includes("case_law") || !next.length ? value.courts : [] });
  };
  const toggleCourt = (code: string) => {
    const next = value.courts.includes(code) ? value.courts.filter((c) => c !== code) : [...value.courts, code];
    onChange({ ...value, courts: next });
  };
  const setYear = (field: "year_from" | "year_to", raw: string) => {
    const parsed = raw === "" ? null : Number.parseInt(raw, 10);
    onChange({ ...value, [field]: Number.isNaN(parsed) ? null : parsed });
  };

  return (
    <div className="flex flex-col gap-6 text-sm">
      <fieldset>
        <legend className="mb-2 font-medium">Sources</legend>
        <div className="flex flex-col gap-1.5">
          {sources.map((source) => (
            <label key={source.key} className="flex cursor-pointer items-baseline gap-2.5">
              <input
                type="checkbox"
                className="translate-y-px accent-red"
                checked={!value.collections.length || value.collections.includes(source.key)}
                onChange={() => toggleCollection(source.key)}
              />
              <span className="min-w-0 flex-1 truncate">
                {source.label}
                <span className="ml-1.5 font-mono text-xs text-ink-3 tabular">
                  {source.count.toLocaleString()}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {caseLaw && caseLaw.courts.length > 0 && (
        <fieldset disabled={!caseLawAllowed} className="disabled:opacity-50">
          <legend className="mb-2 font-medium">Courts</legend>
          <div className="flex flex-col gap-1.5">
            {caseLaw.courts.map((court) => (
              <label key={court.code} className="flex cursor-pointer items-baseline gap-2.5">
                <input
                  type="checkbox"
                  className="translate-y-px accent-red"
                  checked={value.courts.includes(court.code)}
                  onChange={() => toggleCourt(court.code)}
                />
                <span className="flex-1 leading-snug">
                  {court.name}
                  <span className="ml-1.5 font-mono text-xs text-ink-3 tabular">{court.documents}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-ink-3">None ticked means every court.</p>
        </fieldset>
      )}

      <fieldset>
        <legend className="mb-2 font-medium">Years</legend>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="year-from">
            From
          </label>
          <input
            id="year-from"
            type="number"
            inputMode="numeric"
            min={yearMin}
            max={yearMax}
            placeholder="from"
            value={value.year_from ?? ""}
            onChange={(event) => setYear("year_from", event.target.value)}
            className="w-full min-w-0 rounded-control border border-rule-2 bg-sheet px-2.5 py-1.5 font-mono text-sm tabular placeholder:text-ink-3 focus:border-ink-3 focus:outline-none"
          />
          <span className="text-ink-3" aria-hidden="true">
            –
          </span>
          <label className="sr-only" htmlFor="year-to">
            To
          </label>
          <input
            id="year-to"
            type="number"
            inputMode="numeric"
            min={yearMin}
            max={yearMax}
            placeholder="to"
            value={value.year_to ?? ""}
            onChange={(event) => setYear("year_to", event.target.value)}
            className="w-full min-w-0 rounded-control border border-rule-2 bg-sheet px-2.5 py-1.5 font-mono text-sm tabular placeholder:text-ink-3 focus:border-ink-3 focus:outline-none"
          />
        </div>
        {yearMin && yearMax && (
          <p className="mt-2 font-mono text-xs text-ink-3 tabular">
            {yearMin}–{yearMax}
          </p>
        )}
      </fieldset>

      {!isDefault && (
        <button
          type="button"
          onClick={() => onChange({ collections: [], courts: [], year_from: null, year_to: null })}
          className="self-start text-sm text-red underline-offset-2 hover:underline"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}

function RailSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-hidden="true">
      {[3, 7, 1].map((rows, i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="skeleton h-3.5 w-16" />
          {Array.from({ length: rows }).map((_, j) => (
            <div key={j} className="skeleton h-3.5 w-[70%]" />
          ))}
        </div>
      ))}
    </div>
  );
}
