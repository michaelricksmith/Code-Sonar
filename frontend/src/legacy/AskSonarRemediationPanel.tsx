import { useEffect, useState } from "react";

import {
  approveAndRunRemediation,
  fetchRemediationPlan,
} from "../api/askSonar";
import type {
  ApproveRemediationResponse,
  RemediationPlanResponse,
  RemediationRisk,
} from "../api/askSonar";
import type { Finding } from "../api/analyzers";

interface AskSonarRemediationPanelProps {
  scanId: string | null;
  finding: Finding;
  currentScore: number;
}

const RISK_CLASSES: Record<RemediationRisk, string> = {
  low: "border-sky-700/60 bg-sky-900/20 text-sky-200",
  medium: "border-amber-700/60 bg-amber-900/20 text-amber-200",
  high: "border-rose-700/60 bg-rose-900/20 text-rose-200",
  critical: "border-fuchsia-700/60 bg-fuchsia-900/20 text-fuchsia-200",
};

function requestId(scanId: string, findingId: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  return `ask-sonar-${scanId.slice(0, 10)}-${findingId.slice(0, 10)}-${suffix}`;
}

export function AskSonarRemediationPanel({
  scanId,
  finding,
  currentScore,
}: AskSonarRemediationPanelProps) {
  const [planResponse, setPlanResponse] = useState<RemediationPlanResponse | null>(null);
  const [workflowResponse, setWorkflowResponse] = useState<ApproveRemediationResponse | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPlanResponse(null);
    setWorkflowResponse(null);
    setError(null);
    setLoadingPlan(false);
    setRunning(false);
  }, [scanId, finding.id]);

  async function buildPlan(): Promise<void> {
    if (!scanId) return;
    setLoadingPlan(true);
    setError(null);
    setWorkflowResponse(null);
    try {
      setPlanResponse(await fetchRemediationPlan(scanId, finding.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingPlan(false);
    }
  }

  async function approveAndRun(): Promise<void> {
    if (!scanId || !planResponse) return;
    setRunning(true);
    setError(null);
    try {
      const response = await approveAndRunRemediation({
        requestId: requestId(scanId, finding.id),
        scanId,
        findingId: finding.id,
        planId: planResponse.plan.plan_id,
      });
      setWorkflowResponse(response);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  if (!scanId) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
        <div className="text-sm font-semibold text-slate-200">Ask Sonar remediation</div>
        <p className="mt-1 text-xs text-slate-400">
          This scan was not persisted to history, so Code Sonar cannot safely bind an
          executable plan to it. Run the scan again before requesting remediation.
        </p>
      </div>
    );
  }

  const validation = workflowResponse?.workflow.validation ?? null;
  const execution = workflowResponse?.workflow.execution ?? null;
  const afterScore = validation ? currentScore + validation.score_delta : null;

  return (
    <div className="rounded-lg border border-sky-800/60 bg-sky-950/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-sky-100">Ask Sonar remediation</div>
          <p className="mt-1 text-xs text-slate-400">
            Plans are grounded in the persisted finding. Execution requires a separate
            approval and runs only in an isolated Code Sonar worktree.
          </p>
        </div>
        {!planResponse && (
          <button
            type="button"
            onClick={buildPlan}
            disabled={loadingPlan || running}
            className="shrink-0 rounded-md bg-sky-600 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
          >
            {loadingPlan ? "Building plan…" : "Build fix plan"}
          </button>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-rose-700/60 bg-rose-900/30 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {planResponse && !workflowResponse && (
        <div className="mt-4 space-y-3">
          <div className={`rounded-md border p-3 ${RISK_CLASSES[planResponse.plan.risk_level]}`}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold uppercase tracking-wide">
                {planResponse.plan.risk_level} risk
              </span>
              <code className="text-[10px] opacity-80">{planResponse.plan.plan_id}</code>
            </div>
            <p className="mt-2 text-sm">{planResponse.plan.summary}</p>
          </div>

          <div className="grid gap-3 text-xs md:grid-cols-2">
            <div className="rounded-md bg-slate-900/70 p-3">
              <div className="uppercase tracking-wide text-slate-500">Target files</div>
              <div className="mt-1 space-y-1 font-mono text-slate-200">
                {planResponse.plan.expected_files.map((file) => (
                  <div key={file}>{file}</div>
                ))}
              </div>
            </div>
            <div className="rounded-md bg-slate-900/70 p-3">
              <div className="uppercase tracking-wide text-slate-500">Verification</div>
              <div className="mt-1 text-slate-200">
                Validation + deterministic rescan required
              </div>
              <div className="mt-1 text-slate-400">
                Score impact is unknown until the rescan completes.
              </div>
            </div>
          </div>

          <div className="rounded-md bg-slate-900/70 p-3 text-xs">
            <div className="uppercase tracking-wide text-slate-500">Proposed instruction</div>
            <p className="mt-1 whitespace-pre-wrap text-slate-200">
              {planResponse.plan.instruction}
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-700/70 pt-3">
            <p className="max-w-md text-xs text-amber-200">
              Approval will allow the configured executor to modify the isolated worktree.
              Code Sonar will not commit, push, or merge the result automatically.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPlanResponse(null)}
                disabled={running}
                className="rounded-md border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={approveAndRun}
                disabled={running}
                className="rounded-md bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-700"
              >
                {running ? "Running remediation…" : "Approve & run"}
              </button>
            </div>
          </div>
        </div>
      )}

      {workflowResponse && (
        <div className="mt-4 space-y-3">
          <div
            className={`rounded-md border p-3 ${
              workflowResponse.workflow.completed
                ? "border-emerald-700/60 bg-emerald-900/20"
                : "border-amber-700/60 bg-amber-900/20"
            }`}
          >
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-300">
              {workflowResponse.workflow.completed ? "Workflow completed" : "Workflow stopped"}
            </div>
            {validation && (
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                <div>
                  <div className="text-xs text-slate-500">Finding</div>
                  <div className={validation.finding_resolved ? "text-emerald-300" : "text-rose-300"}>
                    {validation.finding_resolved ? "Resolved" : "Still present"}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Score</div>
                  <div className="text-slate-100">
                    {currentScore} → {afterScore}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Debt</div>
                  <div className={validation.debt_points_delta <= 0 ? "text-emerald-300" : "text-rose-300"}>
                    {validation.debt_points_delta > 0 ? "+" : ""}{validation.debt_points_delta} pts
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Regression</div>
                  <div className={validation.regression_detected ? "text-rose-300" : "text-emerald-300"}>
                    {validation.regression_detected ? "Detected" : "None"}
                  </div>
                </div>
              </div>
            )}
          </div>

          {execution && (
            <div className="rounded-md bg-slate-900/70 p-3 text-xs">
              <div className="flex flex-wrap justify-between gap-2">
                <span className="text-slate-400">
                  Executor: <span className="text-slate-200">{execution.executor_name}</span>
                </span>
                <span className="text-slate-400">
                  State: <span className="text-slate-200">{execution.state}</span>
                </span>
              </div>
              {execution.changed_files.length > 0 && (
                <div className="mt-2">
                  <div className="uppercase tracking-wide text-slate-500">Git-observed changes</div>
                  <div className="mt-1 space-y-1 font-mono text-slate-200">
                    {execution.changed_files.map((file) => <div key={file}>{file}</div>)}
                  </div>
                </div>
              )}
            </div>
          )}

          {validation && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-md bg-slate-900/70 p-3">
                Build: {validation.build_passed == null ? "not configured" : validation.build_passed ? "passed" : "failed"}
              </div>
              <div className="rounded-md bg-slate-900/70 p-3">
                Tests: {validation.tests_passed == null ? "not configured" : validation.tests_passed ? "passed" : "failed"}
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={buildPlan}
            disabled={loadingPlan || running}
            className="rounded-md border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            Build fresh plan
          </button>
        </div>
      )}
    </div>
  );
}
