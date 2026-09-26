/**
 * FixesView — the fix log. Every guided fix Sonar has run on this repo,
 * newest first: what was fixed, whether it held, and what the score did.
 *
 * Finding titles come from each outcome's before-scan record, so the log
 * still names findings that are long since resolved.
 */

import { useEffect, useMemo, useState } from "react";

import { timeAgo } from "../copy";
import { issueCardTitle } from "../copy/issues";
import { fetchFixLog, type RemediationOutcomeRecord } from "../api/outcomes";
import { fetchPromptStatus, type PromptStatusItem } from "../api/prompts";
import type { Finding } from "../api/analyzers";

interface ResolvedFix {
  outcome: RemediationOutcomeRecord;
  title: string;
  filePath: string;
  severity: string;
}

async function fetchScanFindings(scanId: string): Promise<Finding[]> {
  const response = await fetch(`/api/history/${encodeURIComponent(scanId)}`, {
    credentials: "include",
  });
  if (!response.ok) return [];
  const data = (await response.json()) as { findings?: Finding[] };
  return Array.isArray(data.findings) ? data.findings : [];
}

function severityTone(severity: string): string {
  const s = severity.toLowerCase();
  if (s.includes("critical")) return "tone-critical";
  if (s.includes("high") || s === "error") return "tone-attention";
  if (s.includes("medium") || s === "warning") return "tone-ok";
  return "tone-good";
}

export function FixesView({ repoLabel }: { repoLabel: string }) {
  const [outcomes, setOutcomes] = useState<RemediationOutcomeRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<ResolvedFix[]>([]);
  const [resolving, setResolving] = useState(false);
  const [promptItems, setPromptItems] = useState<PromptStatusItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setOutcomes(null);
    setError(null);
    setResolved([]);
    setPromptItems(null);
    fetchFixLog(repoLabel)
      .then((data) => {
        if (!cancelled) setOutcomes(data.outcomes);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Couldn't load the fix log.");
      });
    // Prompt-first fixes: prompts the user copied, reconciled against the
    // latest scan. Best-effort — the auto-apply log below is authoritative.
    fetchPromptStatus(repoLabel)
      .then((items) => {
        if (!cancelled) setPromptItems(items);
      })
      .catch(() => {
        if (!cancelled) setPromptItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [repoLabel]);

  useEffect(() => {
    if (!outcomes || outcomes.length === 0) return;
    let cancelled = false;
    setResolving(true);
    const scanCache = new Map<string, Finding[]>();
    (async () => {
      const items: ResolvedFix[] = [];
      for (const outcome of outcomes) {
        let findings = scanCache.get(outcome.before_scan_id);
        if (findings === undefined) {
          findings = await fetchScanFindings(outcome.before_scan_id);
          scanCache.set(outcome.before_scan_id, findings);
        }
        const finding = findings.find((f) => f.id === outcome.finding_id);
        items.push({
          outcome,
          title: finding ? issueCardTitle(finding) : `Finding ${outcome.finding_id.slice(0, 8)}…`,
          filePath: finding?.file_path ?? "—",
          severity: finding?.severity ?? "—",
        });
      }
      if (!cancelled) {
        setResolved(items);
        setResolving(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [outcomes]);

  const stats = useMemo(() => {
    if (!outcomes) return null;
    const fixed = outcomes.filter((o) => o.successful).length;
    const points = outcomes.reduce((sum, o) => sum + o.score_delta, 0);
    return { total: outcomes.length, fixed, points };
  }, [outcomes]);

  const inProgress = useMemo(
    () => (promptItems ?? []).filter((i) => i.status === "in_progress"),
    [promptItems],
  );

  return (
    <div className="page fixlog">
      <div className="page-head">
        <div>
          <h1>Fixes</h1>
          <p className="sub">Every fix Sonar has run on {repoLabel} — tracked, timestamped, and scored.</p>
        </div>
      </div>

      {error && <div className="notice danger">{error}</div>}

      {!outcomes && !error && (
        <div className="loading-inline">
          <div className="spinner" />
          Loading the fix log…
        </div>
      )}

      {outcomes && outcomes.length === 0 && inProgress.length === 0 && (
        <div className="empty-panel">
          <h2>No fixes yet</h2>
          <p>
            When you copy a fix prompt for an issue, it lands here as “in progress”
            until your next scan confirms the fix.
          </p>
        </div>
      )}

      {stats && stats.total > 0 && (
        <div className="fixlog-stats">
          <div className="fixlog-stat">
            <span className="num">{stats.total}</span>
            <span className="cap">fixes run</span>
          </div>
          <div className="fixlog-stat">
            <span className="num good">{stats.fixed}</span>
            <span className="cap">held clean</span>
          </div>
          <div className="fixlog-stat">
            <span className={`num ${stats.points >= 0 ? "good" : "bad"}`}>
              {stats.points >= 0 ? `+${stats.points}` : stats.points}
            </span>
            <span className="cap">score points moved</span>
          </div>
        </div>
      )}

      {(resolving || (outcomes && outcomes.length > 0 && resolved.length === 0)) && (
        <div className="loading-inline">
          <div className="spinner" />
          Naming the fixes…
        </div>
      )}

      <div className="fixlog-list">
        {inProgress.map((item) => (
          <div key={`${item.rule_id}:${item.file_path}`} className="fixlog-row progress">
            <div className="fixlog-badge progress">◷</div>
            <div className="fixlog-body">
              <div className="fixlog-title">Fix in progress</div>
              <div className="fixlog-meta">
                <span className="mono">{item.file_path}</span>
                <span className="mono">{item.rule_id}</span>
                <span>{timeAgo(item.copied_at)}</span>
                <span>prompt copied — waiting on your next scan</span>
              </div>
            </div>
          </div>
        ))}
        {resolved.map(({ outcome, title, filePath, severity }) => (
          <div key={outcome.outcome_id} className={`fixlog-row ${outcome.successful ? "ok" : "miss"}`}>
            <div className={`fixlog-badge ${outcome.successful ? "ok" : "miss"}`}>
              {outcome.successful ? "✓" : "✗"}
            </div>
            <div className="fixlog-body">
              <div className="fixlog-title">{title}</div>
              <div className="fixlog-meta">
                <span className="mono">{filePath}</span>
                {severity !== "—" && <span className={`sev-chip ${severityTone(severity)}`}>{severity}</span>}
                <span>{timeAgo(outcome.attempted_at)}</span>
                <span className="mono">{outcome.remediation_kind.replace(/_/g, " ")}</span>
              </div>
            </div>
            <div className="fixlog-delta">
              <span className={`delta ${outcome.score_delta > 0 ? "up" : outcome.score_delta < 0 ? "down" : "flat"}`}>
                {outcome.score_delta > 0 ? `+${outcome.score_delta}` : outcome.score_delta}
              </span>
              <span className="cap">score</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
