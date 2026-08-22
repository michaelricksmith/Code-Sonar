// Code Sonar — finding detail drawer/modal.

import { useEffect } from "react";

import type { Finding } from "../api/analyzers";
import { SEVERITY_COLOR, severityRank } from "../api/analyzers";

interface FindingDetailDrawerProps {
  finding: Finding | null;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 text-sm">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="col-span-2 text-slate-100">{value}</div>
    </div>
  );
}

function formatMetadata(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function FindingDetailDrawer({
  finding,
  onClose,
}: FindingDetailDrawerProps) {
  useEffect(() => {
    if (!finding) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [finding, onClose]);

  if (!finding) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-slate-900/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Finding ${finding.id}`}
    >
      <div
        className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-800 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span
                className={
                  "inline-flex rounded px-2 py-0.5 text-xs ring-1 " +
                  SEVERITY_COLOR[finding.severity]
                }
              >
                {finding.severity} (rank {severityRank(finding.severity)})
              </span>
              <code className="text-xs text-slate-400">{finding.rule_id}</code>
            </div>
            <h2 className="mt-2 text-xl font-semibold text-slate-100">
              {finding.message}
            </h2>
            <p className="mt-1 font-mono text-xs text-slate-400">
              {finding.file_path}
              {finding.line_start != null && `:${finding.line_start}`}
              {finding.line_end != null &&
                finding.line_end !== finding.line_start &&
                `–${finding.line_end}`}
              {finding.symbol && (
                <>
                  {" "}
                  · <span className="text-slate-300">{finding.symbol}</span>
                </>
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="mt-6 space-y-4">
          <Row label="ID" value={<code className="text-xs">{finding.id}</code>} />
          <Row label="Analyzer" value={finding.analyzer} />
          <Row label="Category" value={finding.category} />
          <Row
            label="Confidence"
            value={`${(finding.confidence * 100).toFixed(0)}%`}
          />
          <Row
            label="Debt"
            value={
              <span>
                +{finding.debt_points} pts
                {finding.remediation_effort && (
                  <span className="text-slate-400">
                    {" "}
                    · {finding.remediation_effort}
                  </span>
                )}
              </span>
            }
          />
          <Row
            label="Evidence"
            value={
              <pre className="whitespace-pre-wrap break-words rounded-md bg-slate-800/60 p-2 font-mono text-xs text-slate-200">
                {finding.evidence}
              </pre>
            }
          />
          {finding.suggestion && (
            <Row
              label="Suggestion"
              value={
                <p className="text-sm text-slate-200">{finding.suggestion}</p>
              }
            />
          )}
          {Object.keys(finding.metadata ?? {}).length > 0 && (
            <Row
              label="Metadata"
              value={
                <pre className="whitespace-pre-wrap break-words rounded-md bg-slate-800/60 p-2 font-mono text-xs text-slate-300">
                  {Object.entries(finding.metadata)
                    .map(([k, v]) => `${k}: ${formatMetadata(v)}`)
                    .join("\n")}
                </pre>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
