// Code Sonar — sortable findings table.

import { useMemo } from "react";

import type { Finding, SortKey, SortState } from "../api/analyzers";
import { SEVERITY_COLOR, severityRank } from "../api/analyzers";

interface SortableFindingsTableProps {
  findings: Finding[];
  onSelect: (finding: Finding) => void;
  sort: SortState;
  onSortChange: (sort: SortState) => void;
}

interface ColumnDef {
  key: SortKey;
  label: string;
  align?: "left" | "right";
  sortable?: boolean;
}

const COLUMNS: ColumnDef[] = [
  { key: "severity", label: "Severity", sortable: true },
  { key: "file_path", label: "File", sortable: true },
  { key: "line_start", label: "Line", align: "right", sortable: true },
  { key: "analyzer", label: "Analyzer", sortable: true },
  { key: "debt_points", label: "Debt", align: "right", sortable: true },
];

function compareFindings(
  a: Finding,
  b: Finding,
  key: SortKey,
  direction: "asc" | "desc",
): number {
  let cmp = 0;
  switch (key) {
    case "severity":
      cmp = severityRank(a.severity) - severityRank(b.severity);
      break;
    case "file_path":
      cmp = a.file_path.localeCompare(b.file_path);
      break;
    case "debt_points":
      cmp = a.debt_points - b.debt_points;
      break;
    case "line_start":
      cmp = (a.line_start ?? 0) - (b.line_start ?? 0);
      break;
    case "analyzer":
      cmp = a.analyzer.localeCompare(b.analyzer);
      break;
  }
  // Stable secondary sort by file_path + line_start.
  if (cmp === 0 && key !== "file_path") {
    cmp = a.file_path.localeCompare(b.file_path);
  }
  if (cmp === 0 && key !== "line_start") {
    cmp = (a.line_start ?? 0) - (b.line_start ?? 0);
  }
  return direction === "asc" ? cmp : -cmp;
}

export function SortableFindingsTable({
  findings,
  onSelect,
  sort,
  onSortChange,
}: SortableFindingsTableProps) {
  const sorted = useMemo(
    () => [...findings].sort((a, b) => compareFindings(a, b, sort.key, sort.direction)),
    [findings, sort],
  );

  const toggleSort = (key: SortKey) => {
    if (sort.key === key) {
      onSortChange({
        key,
        direction: sort.direction === "asc" ? "desc" : "asc",
      });
    } else {
      onSortChange({ key, direction: "asc" });
    }
  };

  return (
    <div className="overflow-x-auto rounded-md border border-slate-800">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-slate-800/60 text-xs uppercase tracking-wide text-slate-400">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className={
                  "px-3 py-2 " +
                  (col.align === "right" ? "text-right " : "text-left ") +
                  (col.sortable ? "cursor-pointer hover:text-slate-200 " : "")
                }
                onClick={col.sortable ? () => toggleSort(col.key) : undefined}
              >
                {col.label}
                {col.sortable && sort.key === col.key && (
                  <span className="ml-1 text-slate-500">
                    {sort.direction === "asc" ? "▲" : "▼"}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {sorted.length === 0 && (
            <tr>
              <td
                colSpan={COLUMNS.length}
                className="px-3 py-4 text-center text-sm text-slate-400"
              >
                No findings match the current filters.
              </td>
            </tr>
          )}
          {sorted.map((f) => (
            <tr
              key={f.id}
              onClick={() => onSelect(f)}
              className="cursor-pointer bg-slate-900/40 transition-colors hover:bg-slate-800/60"
            >
              <td className="px-3 py-2">
                <span
                  className={
                    "inline-flex rounded px-2 py-0.5 text-xs ring-1 " +
                    SEVERITY_COLOR[f.severity]
                  }
                >
                  {f.severity}
                </span>
              </td>
              <td className="px-3 py-2 font-mono text-xs text-slate-200">
                {f.file_path}
                {f.line_start != null && (
                  <span className="text-slate-500">:{f.line_start}</span>
                )}
              </td>
              <td className="px-3 py-2 text-right text-slate-300">
                {f.line_start ?? "—"}
              </td>
              <td className="px-3 py-2 text-xs text-slate-300">
                {f.analyzer}
              </td>
              <td className="px-3 py-2 text-right text-slate-200">
                +{f.debt_points}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
