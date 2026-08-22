// Code Sonar — severity / category / analyzer filter chips.

import { useMemo } from "react";

import type {
  AnalyzerMetadata,
  Category,
  Finding,
  FilterState,
  Severity,
} from "../api/analyzers";
import {
  CATEGORIES,
  SEVERITIES,
  SEVERITY_COLOR,
} from "../api/analyzers";

interface FilterChipsProps {
  findings: Finding[];
  analyzers: AnalyzerMetadata[];
  filter: FilterState;
  onChange: (next: FilterState) => void;
}

interface ChipProps {
  active: boolean;
  label: string;
  count: number;
  onClick: () => void;
  className?: string;
}

function Chip({ active, label, count, onClick, className }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 transition-colors " +
        (active
          ? "bg-sky-600/30 text-sky-100 ring-sky-500/60 hover:bg-sky-600/40 "
          : "bg-slate-800/60 text-slate-400 ring-slate-700 hover:bg-slate-800 ") +
        (className ?? "")
      }
      aria-pressed={active}
    >
      <span>{label}</span>
      <span className="rounded-full bg-slate-900/60 px-1.5 text-[10px] text-slate-300">
        {count}
      </span>
    </button>
  );
}

function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

export function FilterChips({
  findings,
  analyzers,
  filter,
  onChange,
}: FilterChipsProps) {
  const counts = useMemo(() => {
    const bySeverity = new Map<Severity, number>();
    const byCategory = new Map<Category, number>();
    const byAnalyzer = new Map<string, number>();
    for (const f of findings) {
      bySeverity.set(f.severity, (bySeverity.get(f.severity) ?? 0) + 1);
      byCategory.set(f.category, (byCategory.get(f.category) ?? 0) + 1);
      byAnalyzer.set(f.analyzer, (byAnalyzer.get(f.analyzer) ?? 0) + 1);
    }
    return { bySeverity, byCategory, byAnalyzer };
  }, [findings]);

  const analyzerNames = analyzers.map((a) => a.analyzer_id);

  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
          Severity
        </div>
        <div className="flex flex-wrap gap-2">
          {SEVERITIES.map((s) => (
            <Chip
              key={s}
              active={filter.severities.has(s)}
              label={s}
              count={counts.bySeverity.get(s) ?? 0}
              className={filter.severities.has(s) ? SEVERITY_COLOR[s] : ""}
              onClick={() =>
                onChange({ ...filter, severities: toggle(filter.severities, s) })
              }
            />
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
          Category
        </div>
        <div className="flex flex-wrap gap-2">
          {CATEGORIES.map((c) => (
            <Chip
              key={c}
              active={filter.categories.has(c)}
              label={c}
              count={counts.byCategory.get(c) ?? 0}
              onClick={() =>
                onChange({ ...filter, categories: toggle(filter.categories, c) })
              }
            />
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
          Analyzer
        </div>
        <div className="flex flex-wrap gap-2">
          {analyzerNames.map((name) => (
            <Chip
              key={name}
              active={filter.analyzers.has(name)}
              label={name}
              count={counts.byAnalyzer.get(name) ?? 0}
              onClick={() =>
                onChange({ ...filter, analyzers: toggle(filter.analyzers, name) })
              }
            />
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
          Search
        </label>
        <input
          type="text"
          placeholder="file, symbol, evidence, message…"
          value={filter.search}
          onChange={(e) => onChange({ ...filter, search: e.target.value })}
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
        />
      </div>
    </div>
  );
}
