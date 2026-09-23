import { useEffect, useMemo, useState } from "react";

import {
  askSonar,
  fetchAskSonarStatus,
  type AskSonarStatus,
  type GroundedAnswerResponse,
} from "../api/askSonar";
import type { Finding, ScanResponse } from "../api/analyzers";

function priorityFindings(findings: Finding[]): Finding[] {
  const severityWeight: Record<Finding["severity"], number> = {
    critical: 4,
    error: 3,
    warning: 2,
    info: 1,
  };
  return [...findings]
    .sort((a, b) => {
      const severityDelta = severityWeight[b.severity] - severityWeight[a.severity];
      if (severityDelta !== 0) return severityDelta;
      if (b.debt_points !== a.debt_points) return b.debt_points - a.debt_points;
      return a.file_path.localeCompare(b.file_path);
    })
    .slice(0, 3);
}

export function FirstScanGuide({
  result,
  onSelectFinding,
}: {
  result: ScanResponse;
  onSelectFinding: (finding: Finding) => void;
}) {
  const [status, setStatus] = useState<AskSonarStatus | null>(null);
  const [answer, setAnswer] = useState<GroundedAnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const priorities = useMemo(() => priorityFindings(result.findings), [result.findings]);

  useEffect(() => {
    let active = true;
    fetchAskSonarStatus()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch(() => {
        if (active) setStatus(null);
      });
    return () => {
      active = false;
    };
  }, [result.scan_id]);

  async function explainScore(): Promise<void> {
    if (!result.scan_id) return;
    setLoading(true);
    setError(null);
    try {
      const response = await askSonar({
        scanId: result.scan_id,
        question:
          "Explain this Code Sonar score to a new user. Summarize the main debt drivers, the highest-priority findings, and what I should inspect first. Keep deterministic Code Sonar scoring authoritative.",
      });
      setAnswer(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-lg border border-sky-800/70 bg-sky-950/20 p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-400">
            Ask Sonar · First scan
          </div>
          <h2 className="mt-1 text-xl font-semibold text-slate-100">
            Your codebase baseline is ready
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">
            Code Sonar scored this repository at {result.score} ({result.grade}) with{" "}
            {result.finding_count} findings and {result.total_debt_points} debt points. The score is
            deterministic; Ask Sonar can explain the evidence but cannot change the score.
          </p>
        </div>
        <div className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-400">
          {status?.configured ? (
            <>
              AI explanation ready · {status.provider}/{status.model}
            </>
          ) : (
            <>Deterministic guidance available · AI provider not configured</>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {priorities.length === 0 ? (
          <div className="md:col-span-3 rounded-md border border-emerald-800/60 bg-emerald-950/20 p-4 text-sm text-emerald-200">
            No findings were detected in this scan. Run future scans to establish drift history.
          </div>
        ) : (
          priorities.map((finding, index) => (
            <button
              key={finding.id}
              type="button"
              onClick={() => onSelectFinding(finding)}
              className="rounded-md border border-slate-700 bg-slate-900/60 p-4 text-left hover:border-sky-700 hover:bg-slate-900"
            >
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Priority {index + 1}
              </div>
              <div className="mt-1 text-sm font-semibold text-slate-200">{finding.message}</div>
              <div className="mt-2 text-xs text-slate-500">
                {finding.severity} · {finding.debt_points} debt points · {finding.file_path}
              </div>
            </button>
          ))
        )}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={explainScore}
          disabled={!result.scan_id || !status?.configured || loading}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {loading ? "Ask Sonar is reading the scan…" : "Explain my score"}
        </button>
        {!result.scan_id && (
          <span className="text-xs text-amber-300">
            This scan was not persisted, so grounded Ask Sonar questions are disabled.
          </span>
        )}
        {result.scan_id && status && !status.configured && (
          <span className="text-xs text-slate-500">
            Configure an approved Ask Sonar provider to enable conversational explanations.
          </span>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-rose-800/60 bg-rose-950/30 p-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      {answer && (
        <div className="mt-5 rounded-md border border-slate-700 bg-slate-900/70 p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-semibold text-slate-200">Ask Sonar explanation</div>
            <div className="text-xs text-slate-500">
              {answer.answer.provider_name}/{answer.answer.model_name}
            </div>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-300">
            {answer.answer.answer}
          </p>
          <div className="mt-3 text-xs text-slate-500">
            Grounded sources: {answer.answer.used_sources.join(", ") || "deterministic scan context"}
          </div>
        </div>
      )}
    </section>
  );
}
