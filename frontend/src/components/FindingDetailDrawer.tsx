// Code Sonar — finding detail drawer/modal.
//
// Lane 4 (Checkpoint 5): security-finding UX. For SECURITY
// findings, the drawer renders an explicit "Why this was redacted"
// section that never echoes the live credential. The raw evidence
// field is suppressed; instead the surrounding context is shown via
// the analyzer's `safe_context` metadata when present, falling back
// to a clear redacted marker.

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

function isSecurityFinding(finding: Finding): boolean {
  return finding.category === "security";
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

  const isSecurity = isSecurityFinding(finding);
  const safeContext =
    typeof finding.metadata?.["safe_context"] === "string"
      ? (finding.metadata["safe_context"] as string)
      : null;
  const redactedReason =
    typeof finding.metadata?.["redaction_reason"] === "string"
      ? (finding.metadata["redaction_reason"] as string)
      : "Evidence may contain a live credential and is not shown verbatim.";

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
            label="File / location"
            value={
              <span className="font-mono text-xs">
                {finding.file_path}
                {finding.line_start != null && `:${finding.line_start}`}
                {finding.line_end != null &&
                  finding.line_end !== finding.line_start &&
                  `–${finding.line_end}`}
              </span>
            }
          />
          <Row
            label="Severity"
            value={
              <span>
                <span
                  className={
                    "inline-flex rounded px-2 py-0.5 text-xs ring-1 mr-2 " +
                    SEVERITY_COLOR[finding.severity]
                  }
                >
                  {finding.severity}
                </span>
                rank {severityRank(finding.severity)}
              </span>
            }
          />
          <Row
            label="Confidence"
            value={`${(finding.confidence * 100).toFixed(0)}%`}
          />
          <Row
            label="Debt impact"
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

          {/* Security findings: redacted evidence section. */}
          {isSecurity && (
            <div className="rounded-md border border-rose-700/40 bg-rose-900/20 p-3 text-sm">
              <div className="text-xs uppercase tracking-wide text-rose-300">
                Why this evidence was redacted
              </div>
              <p className="mt-1 text-rose-100">{redactedReason}</p>
              {safeContext && (
                <div className="mt-3">
                  <div className="text-xs uppercase tracking-wide text-rose-300">
                    Safe surrounding context
                  </div>
                  <pre className="mt-1 whitespace-pre-wrap break-words rounded-md bg-slate-950/60 p-2 font-mono text-xs text-slate-200">
                    {safeContext}
                  </pre>
                </div>
              )}
              <div className="mt-3 text-xs text-rose-200/80">
                The live credential is <strong>never</strong> shown in this
                view. Revoke the leaked value, store the replacement in your
                secrets manager, and reference it via environment variables at
                runtime.
              </div>
            </div>
          )}

          {/* Non-security findings: show evidence as-is. */}
          {!isSecurity && (
            <Row
              label="Evidence"
              value={
                <pre className="whitespace-pre-wrap break-words rounded-md bg-slate-800/60 p-2 font-mono text-xs text-slate-200">
                  {finding.evidence}
                </pre>
              }
            />
          )}

          {finding.suggestion && (
            <Row
              label="Remediation"
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
                    .filter(
                      ([k]) =>
                        !(
                          isSecurity &&
                          (k === "safe_context" || k === "redaction_reason")
                        ),
                    )
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
