import { useEffect, useMemo, useState } from "react";

import type { DriftResult, Finding, ScanResponse } from "../api/analyzers";
import {
  fetchProjectDashboard,
  fetchProjectDrift,
  fetchProjects,
  scanProject,
} from "../api/projects";
import type { ProjectDashboard, ProjectRecord } from "../api/projects";

function riskRank(finding: Finding): number {
  const severity = { info: 1, warning: 2, error: 4, critical: 8 }[finding.severity];
  return severity * finding.debt_points * finding.confidence;
}

export function ProjectDashboardPanel() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [dashboard, setDashboard] = useState<ProjectDashboard | null>(null);
  const [scanResult, setScanResult] = useState<ScanResponse | null>(null);
  const [drift, setDrift] = useState<DriftResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProjects()
      .then((items) => {
        setProjects(items);
        if (items.length > 0) setProjectId((current) => current || items[0].project_id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!projectId) {
      setDashboard(null);
      return;
    }
    setError(null);
    fetchProjectDashboard(projectId)
      .then(setDashboard)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [projectId]);

  const latest = scanResult ?? dashboard?.latest_scan ?? null;
  const topFindings = useMemo(() => {
    if (!latest?.findings) return [] as Finding[];
    return [...latest.findings].sort((a, b) => riskRank(b) - riskRank(a)).slice(0, 5);
  }, [latest]);

  async function runProjectScan(): Promise<void> {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    setDrift(null);
    try {
      const result = await scanProject(projectId);
      setScanResult(result);
      setDashboard(await fetchProjectDashboard(projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadDrift(): Promise<void> {
    if (!projectId) return;
    setError(null);
    try {
      setDrift(await fetchProjectDrift(projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (projects.length === 0 && !error) {
    return (
      <section className="rounded-lg border border-sky-900/60 bg-sky-950/20 p-5">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-400">
          Projects
        </div>
        <h2 className="mt-1 text-lg font-semibold">No connected projects yet</h2>
        <p className="mt-2 text-sm text-slate-400">
          Connect a GitHub repository first. Once connected, scans, history, and score tracking run from a stable Code Sonar project ID instead of a browser-supplied filesystem path.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-sky-800/60 bg-sky-950/20 p-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-400">
            Project dashboard
          </div>
          <label className="mt-2 block text-xs text-slate-400">Connected repository</label>
          <select
            value={projectId}
            onChange={(e) => {
              setProjectId(e.target.value);
              setScanResult(null);
              setDrift(null);
            }}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 md:max-w-md"
          >
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.full_name} · {project.default_branch}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={loadDrift}
            disabled={!projectId || (dashboard?.history_count ?? 0) < 2}
            className="rounded-md border border-slate-700 px-3 py-2 text-sm font-semibold text-slate-200 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Compare drift
          </button>
          <button
            type="button"
            onClick={runProjectScan}
            disabled={!projectId || loading}
            className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
          >
            {loading ? "Scanning project…" : "Scan project"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-rose-700 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      {dashboard && (
        <div className="mt-5 space-y-5">
          <div className="flex flex-wrap gap-2 text-xs text-slate-400">
            <span className="rounded bg-slate-900 px-2 py-1">{dashboard.project.full_name}</span>
            <span className="rounded bg-slate-900 px-2 py-1">branch {dashboard.project.default_branch}</span>
            <span className="rounded bg-slate-900 px-2 py-1">{dashboard.history_count} scans</span>
            <span className="rounded bg-slate-900 px-2 py-1">score authority: Code Sonar</span>
          </div>

          {latest ? (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="Score" value={String(latest.score)} />
                <Metric label="Grade" value={latest.grade} />
                <Metric label="Findings" value={String(latest.finding_count)} />
                <Metric label="Debt points" value={String(latest.total_debt_points)} />
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-md border border-slate-800 bg-slate-900/50 p-4">
                  <h3 className="text-sm font-semibold">Highest-priority findings</h3>
                  {topFindings.length === 0 ? (
                    <p className="mt-2 text-sm text-emerald-300">No findings in the latest scan.</p>
                  ) : (
                    <div className="mt-3 space-y-2">
                      {topFindings.map((finding) => (
                        <div key={finding.id} className="rounded border border-slate-800 p-3">
                          <div className="flex items-center justify-between gap-3 text-xs">
                            <span className="font-semibold text-slate-200">{finding.rule_id}</span>
                            <span className="text-slate-400">{finding.debt_points} debt</span>
                          </div>
                          <div className="mt-1 truncate text-xs text-slate-400">{finding.file_path}</div>
                          <div className="mt-1 text-sm text-slate-300">{finding.message}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-md border border-slate-800 bg-slate-900/50 p-4">
                  <h3 className="text-sm font-semibold">Recent score history</h3>
                  {dashboard.history.length === 0 ? (
                    <p className="mt-2 text-sm text-slate-400">Run the first project scan to establish a baseline.</p>
                  ) : (
                    <div className="mt-3 space-y-2">
                      {[...dashboard.history].reverse().slice(0, 6).map((scan) => (
                        <div key={scan.scan_id} className="flex items-center justify-between text-sm">
                          <span className="text-slate-400">{new Date(scan.scanned_at).toLocaleString()}</span>
                          <span className="font-semibold text-slate-200">{scan.score} · {scan.grade}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="rounded-md border border-amber-800/60 bg-amber-950/20 p-4 text-sm text-amber-200">
              This project is connected but has no persisted scans yet. Run “Scan project” to establish its deterministic baseline.
            </div>
          )}

          {drift && (
            <div className="rounded-md border border-slate-800 bg-slate-900/50 p-4">
              <h3 className="text-sm font-semibold">Latest drift</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <Metric label="Score delta" value={`${drift.summary.score_delta >= 0 ? "+" : ""}${drift.summary.score_delta}`} />
                <Metric label="Debt delta" value={`${drift.summary.debt_delta >= 0 ? "+" : ""}${drift.summary.debt_delta}`} />
                <Metric label="New / resolved" value={`${drift.summary.new_count} / ${drift.summary.resolved_count}`} />
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-100">{value}</div>
    </div>
  );
}
