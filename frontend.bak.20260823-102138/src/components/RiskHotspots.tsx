/**
 * Risk Hotspots component — Phase 1 of Fastest-Route-to-Private-Beta.
 *
 * Renders the top-N ranked risk hotspots from a Code Sonar scan.
 * Each hotspot card shows:
 *   - file path (click-to-findings)
 *   - score (large)
 *   - severity badge
 *   - finding count + debt total
 *   - analyzer breakdown chips
 *   - explainable signals (complexity, size, nesting) when present
 *
 * Clicking a hotspot filters the findings table to that file's
 * contributing findings (one of the Fastest-Route success criteria:
 * "click-through from hotspot to contributing findings").
 */

import { useMemo, useState } from "react";

import type { Finding, Hotspot, HotspotResult } from "../api/analyzers";

interface RiskHotspotsProps {
  hotspots: Hotspot[];
  hotspotSummary: Pick<
    HotspotResult,
    "total_files" | "files_with_findings" | "total_findings" | "total_debt"
  >;
  findings: Finding[];
  onFilterByFile: (filePath: string | null) => void;
  activeFileFilter: string | null;
}

interface AnomalySummary {
  highestSingleSeverity: { file: string; severity: string; weight: number } | null;
  mostDiverseFile: { file: string; diversity: number } | null;
}

function severityBadgeClasses(severity: string): string {
  switch (severity) {
    case "critical":
      return "bg-rose-900/60 text-rose-200 border-rose-700";
    case "error":
      return "bg-orange-900/60 text-orange-200 border-orange-700";
    case "warning":
      return "bg-amber-900/60 text-amber-200 border-amber-700";
    case "info":
      return "bg-slate-800 text-slate-300 border-slate-600";
    default:
      return "bg-slate-800 text-slate-300 border-slate-600";
  }
}

function scoreTone(score: number): string {
  if (score >= 50) return "text-rose-400";
  if (score >= 25) return "text-orange-400";
  if (score >= 10) return "text-amber-400";
  return "text-emerald-400";
}

export function RiskHotspots({
  hotspots,
  hotspotSummary,
  findings,
  onFilterByFile,
  activeFileFilter,
}: RiskHotspotsProps) {
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  const anomalies = useMemo<AnomalySummary>(() => {
    if (hotspots.length === 0) {
      return { highestSingleSeverity: null, mostDiverseFile: null };
    }
    const sortedByWeight = [...hotspots].sort(
      (a, b) => b.severity_max_weight - a.severity_max_weight,
    );
    const sortedByDiversity = [...hotspots].sort(
      (a, b) => b.analyzer_diversity - a.analyzer_diversity,
    );
    return {
      highestSingleSeverity:
        sortedByWeight.length > 0 && sortedByWeight[0].severity_max_weight >= 3
          ? {
              file: sortedByWeight[0].file_path,
              severity: sortedByWeight[0].severity_max,
              weight: sortedByWeight[0].severity_max_weight,
            }
          : null,
      mostDiverseFile:
        sortedByDiversity.length > 0 && sortedByDiversity[0].analyzer_diversity >= 2
          ? {
              file: sortedByDiversity[0].file_path,
              diversity: sortedByDiversity[0].analyzer_diversity,
            }
          : null,
    };
  }, [hotspots]);

  if (hotspots.length === 0) {
    return (
      <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6 space-y-3">
        <header>
          <h2 className="text-lg font-semibold text-slate-100">
            Risk Hotspots
          </h2>
          <p className="text-xs text-slate-400">
            Which files carry the most risk. Deterministic ranking; explainable
            per-file breakdown. Top {hotspots.length} of {hotspotSummary.files_with_findings}{" "}
            files with findings.
          </p>
        </header>
        <div className="rounded border border-emerald-700 bg-emerald-900/30 p-4 text-sm text-emerald-200">
          🎉 No findings. This scan came back clean.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6 space-y-4">
      <header className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-100">Risk Hotspots</h2>
        <p className="text-xs text-slate-400">
          Ranked by{" "}
          <code className="font-mono text-slate-300">
            debt + severity_max_weight + finding_count + analyzer_diversity×2
          </code>
          . Click any file to filter the findings table below to that
          file's contributing findings.
        </p>
        <div className="flex flex-wrap gap-3 text-xs text-slate-400 pt-1">
          <span>
            <span className="text-slate-200 font-semibold">
              {hotspotSummary.files_with_findings}
            </span>{" "}
            file{hotspotSummary.files_with_findings === 1 ? "" : "s"} with
            findings
          </span>
          <span>·</span>
          <span>
            <span className="text-slate-200 font-semibold">
              {hotspotSummary.total_findings}
            </span>{" "}
            total findings
          </span>
          <span>·</span>
          <span>
            <span className="text-slate-200 font-semibold">
              {hotspotSummary.total_debt}
            </span>{" "}
            debt points
          </span>
        </div>
        {activeFileFilter !== null && (
          <button
            type="button"
            onClick={() => onFilterByFile(null)}
            className="text-xs text-emerald-400 hover:text-emerald-300 underline"
          >
            ✕ Clear file filter ({activeFileFilter})
          </button>
        )}
      </header>

      {anomalies.highestSingleSeverity && (
        <div className="rounded border border-rose-700 bg-rose-900/20 p-3 text-sm text-rose-200">
          ⚠ <span className="font-semibold">{anomalies.highestSingleSeverity.file}</span>{" "}
          contains a{" "}
          <span className="font-semibold">
            {anomalies.highestSingleSeverity.severity}
          </span>{" "}
          finding — single high-severity findings dominate the hotspot
          ranking.
        </div>
      )}
      {anomalies.mostDiverseFile && (
        <div className="rounded border border-amber-700 bg-amber-900/20 p-3 text-sm text-amber-200">
          ◐ <span className="font-semibold">{anomalies.mostDiverseFile.file}</span>{" "}
          is flagged by{" "}
          <span className="font-semibold">
            {anomalies.mostDiverseFile.diversity} different analyzers
          </span>{" "}
          — multiple signals agree this file is high-risk.
        </div>
      )}

      <ol className="space-y-3">
        {hotspots.map((h, idx) => {
          const isActive = activeFileFilter === h.file_path;
          const isExpanded = expandedFile === h.file_path;
          const findingsForFile = findings.filter(
            (f) => f.file_path === h.file_path,
          );
          return (
            <li
              key={h.file_path}
              data-testid={`hotspot-${idx}`}
              className={`rounded-lg border p-4 transition-colors ${
                isActive
                  ? "border-emerald-500 bg-emerald-900/20"
                  : "border-slate-700 bg-slate-900/40 hover:border-slate-600"
              }`}
            >
              <button
                type="button"
                onClick={() => onFilterByFile(isActive ? null : h.file_path)}
                className="w-full text-left"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-slate-500 font-mono">
                        #{idx + 1}
                      </span>
                      <code className="text-sm font-mono text-slate-100 truncate">
                        {h.file_path}
                      </code>
                      <span
                        className={`text-xs px-2 py-0.5 rounded border ${severityBadgeClasses(
                          h.severity_max,
                        )}`}
                      >
                        {h.severity_max}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
                      <span>
                        <span className="text-slate-300">{h.finding_count}</span>{" "}
                        findings
                      </span>
                      <span>
                        <span className="text-slate-300">{h.debt_total}</span>{" "}
                        debt
                      </span>
                      <span>
                        <span className="text-slate-300">
                          {h.analyzer_diversity}
                        </span>{" "}
                        analyzer{h.analyzer_diversity === 1 ? "" : "s"}
                      </span>
                      {h.complexity_max > 0 && (
                        <span title="max cyclomatic complexity in this file">
                          CC≤{h.complexity_max}
                        </span>
                      )}
                      {h.size_max > 0 && (
                        <span title="max lines in a single function/file">
                          {h.size_max} lines
                        </span>
                      )}
                      {h.nesting_max > 0 && (
                        <span title="max nesting depth">
                          depth≤{h.nesting_max}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div
                      className={`text-3xl font-bold ${scoreTone(h.score)}`}
                      title="hotspot score = debt + severity_max_weight + finding_count + analyzer_diversity × 2"
                    >
                      {h.score}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-1">
                      score
                    </div>
                  </div>
                </div>
              </button>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {Object.entries(h.analyzer_breakdown).map(([name, count]) => (
                  <span
                    key={name}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300"
                    title={`${count} finding(s) from analyzer ${name}`}
                  >
                    {name} ×{count}
                  </span>
                ))}
              </div>
              {findingsForFile.length > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    setExpandedFile(isExpanded ? null : h.file_path)
                  }
                  className="mt-3 text-xs text-slate-400 hover:text-slate-200"
                >
                  {isExpanded ? "▾" : "▸"} {findingsForFile.length}{" "}
                  contributing finding{findingsForFile.length === 1 ? "" : "s"}
                </button>
              )}
              {isExpanded && (
                <ul className="mt-2 space-y-1 text-xs">
                  {findingsForFile.map((f) => (
                    <li
                      key={f.id}
                      className="rounded border border-slate-700 bg-slate-900 p-2 font-mono text-slate-300"
                    >
                      <span className="text-slate-500">{f.rule_id}</span>
                      <span className="mx-2">·</span>
                      <span>{f.severity}</span>
                      <span className="mx-2">·</span>
                      <span>debt={f.debt_points}</span>
                      {f.symbol && (
                        <>
                          <span className="mx-2">·</span>
                          <span className="text-emerald-300">{f.symbol}</span>
                        </>
                      )}
                      {f.line_start !== null && (
                        <span className="ml-2 text-slate-500">
                          :{f.line_start}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
