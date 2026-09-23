/**
 * Dashboard — scan results (§2.4 screen 3, mockup-dashboard.html).
 * Score hero with dial + grade chip + verdict + delta, "Fix these first"
 * ranked issue cards, score-over-time, riskiest files, health by area.
 * Plain language throughout; raw data lives in "Details for nerds".
 */

import { useMemo } from "react";

import type { DriftResult, Finding, ScanResponse, Severity } from "../api/analyzers";
import {
  AREA_NOTE,
  AREA_ORDER,
  CATEGORY_AREA,
  GRADE_TONE,
  GRADE_WORDS,
  SEVERITY_LABEL,
  checkSummary,
  confidenceLabel,
  copy,
  deltaText,
  effortLabel,
  gradeForScore,
  locationLabel,
  rawJson,
  timeAgo,
  verdictForScore,
} from "../copy";
import type { HealthArea } from "../copy";
import { issueCardTitle, rankIssues } from "../copy/issues";
import { NerdsDetails } from "./NerdsDetails";
import { ScoreDial } from "./ScoreDial";

interface DashboardProps {
  result: ScanResponse;
  repoLabel: string;
  drift: DriftResult | null;
  onOpenIssue: (finding: Finding) => void;
  onOpenSonar: (question: string) => void;
  onRescan: () => void;
  onAddRepo: () => void;
  onShowAllIssues: () => void;
}

const SEV_ICON: Record<Severity, string> = { critical: "!", error: "◐", warning: "○", info: "✓" };
const SEV_CLASS: Record<Severity, string> = { critical: "urgent", error: "high", warning: "med", info: "low" };
/** Impact dots shown on each issue card. */
const SEVERITY_WEIGHT: Record<Severity, number> = { critical: 8, error: 4, warning: 2, info: 1 };

export function IssueCard({ finding, onOpen }: { finding: Finding; onOpen: (f: Finding) => void }) {
  const sevLabel = SEVERITY_LABEL[finding.severity];
  const effort = effortLabel(finding.remediation_effort);
  return (
    <button className="issue-card" onClick={() => onOpen(finding)} aria-label={`Open issue: ${issueCardTitle(finding)}`}>
      <div className={`sev-ico ${SEV_CLASS[finding.severity]}`}>{SEV_ICON[finding.severity]}</div>
      <div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
          <span className={`sev-chip tone-${SEV_CLASS[finding.severity]}`}>{sevLabel}</span>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {CATEGORY_AREA[finding.category]} · {confidenceLabel(finding.confidence)}
          </span>
        </div>
        <h4>{issueCardTitle(finding)}</h4>
        <p className="plain">{checkSummary(finding.analyzer)}</p>
        <div className="meta">
          <span>📄 <span className="mono">{locationLabel(finding.file_path, finding.line_start, finding.line_end)}</span></span>
          {effort && <span>⏱ {effort} to fix</span>}
        </div>
      </div>
      <div className="fix-col">
        <span className="btn btn-primary btn-sm" style={{ pointerEvents: "none" }}>Fix this</span>
      </div>
    </button>
  );
}

interface FileRisk {
  file_path: string;
  issueCount: number;
  worst: Severity;
  risk: number;
}

function riskiestFiles(findings: Finding[], limit = 3): FileRisk[] {
  const byFile = new Map<string, FileRisk>();
  for (const f of findings) {
    const entry = byFile.get(f.file_path) ?? { file_path: f.file_path, issueCount: 0, worst: "info" as Severity, risk: 0 };
    entry.issueCount += 1;
    entry.risk += SEVERITY_WEIGHT[f.severity] * f.debt_points;
    if (SEVERITY_WEIGHT[f.severity] > SEVERITY_WEIGHT[entry.worst]) entry.worst = f.severity;
    byFile.set(f.file_path, entry);
  }
  return [...byFile.values()].sort((a, b) => b.risk - a.risk).slice(0, limit);
}

function HealthByArea({ result }: { result: ScanResponse }) {
  const areas = useMemo(() => {
    const acc = new Map<HealthArea, { total: number; count: number; issues: number }>();
    for (const [category, score] of Object.entries(result.category_scores)) {
      const area = CATEGORY_AREA[category as keyof typeof CATEGORY_AREA];
      if (!area) continue;
      const entry = acc.get(area) ?? { total: 0, count: 0, issues: 0 };
      entry.total += score;
      entry.count += 1;
      entry.issues += result.findings_by_category[category as keyof typeof result.findings_by_category] ?? 0;
      acc.set(area, entry);
    }
    return AREA_ORDER.map((area) => {
      const entry = acc.get(area);
      const avg = entry && entry.count > 0 ? Math.round(entry.total / entry.count) : null;
      return { area, avg, issues: entry?.issues ?? 0 };
    });
  }, [result]);

  return (
    <div className="panel">
      {areas.map(({ area, avg, issues }) => (
        <div className="health-row" key={area}>
          <div className="hname">{area}</div>
          <div className="htrack">
            <i
              style={{
                width: avg == null ? "0%" : `${Math.max(4, Math.min(100, ((avg - 300) / 550) * 100))}%`,
                background: avg == null ? "#e3dccb" : avg >= 740 ? "var(--good)" : avg >= 580 ? "var(--ok)" : "var(--bad)",
              }}
            />
          </div>
          <div className="hval">{avg == null ? "—" : avg}</div>
          <div className="hnote">{avg == null ? AREA_NOTE[area] : issues === 0 ? `No ${copy.findings} here` : `${issues} ${issues === 1 ? copy.finding : copy.findings}`}</div>
        </div>
      ))}
    </div>
  );
}

export function Dashboard({ result, repoLabel, drift, onOpenIssue, onOpenSonar, onRescan, onAddRepo, onShowAllIssues }: DashboardProps) {
  const ranked = useMemo(() => rankIssues(result.findings), [result]);
  const top = ranked[0] ?? null;
  const grade = gradeForScore(result.score);
  const delta = drift?.summary.score_delta ?? null;
  const files = useMemo(() => riskiestFiles(result.findings), [result]);
  const maxRisk = Math.max(1, ...files.map((f) => f.risk));
  const dist = result.severity_distribution;
  const urgentCount = dist.critical ?? 0;
  const fileCount = new Set(result.findings.map((f) => f.file_path)).size;

  const spark = useMemo(() => {
    if (!drift) return null;
    return [drift.summary.baseline.score, drift.summary.current.score];
  }, [drift]);

  return (
    <div className="page">
      <div className="topbar">
        <div className="crumb">
          Projects / <b>{repoLabel}</b>
        </div>
        <div className="top-actions">
          <button className="btn btn-ghost btn-sm" onClick={onAddRepo}>＋ Add repo</button>
          <button className="btn btn-primary btn-sm" onClick={onRescan}>↻ Re-scan</button>
        </div>
      </div>

      <h1 className="page-title">Code health overview</h1>
      <p className="page-sub">
        Scanned {timeAgo(result.scanned_at)} · {fileCount} {fileCount === 1 ? "file" : "files"} with {copy.findings} · 8 {copy.analyzers} ran · nothing was changed in your repo
      </p>

      <section className="score-hero">
        <div className="score-hero-left">
          <div className="lbl">Sonar score</div>
          <div style={{ display: "flex", justifyContent: "center", margin: "10px 0 2px" }}>
            <ScoreDial score={result.score} width={200} id="dashGrad" />
          </div>
          <div className="num">{result.score}</div>
          <div style={{ marginTop: 6 }}>
            <span className={`grade-chip tone-${GRADE_TONE[grade]}`}>Grade {grade} · {GRADE_WORDS[grade]}</span>
          </div>
          <div className={`score-delta ${delta == null ? "flat" : delta > 0 ? "up" : delta < 0 ? "down" : "flat"}`}>
            {delta == null ? "First scan — no previous score yet" : deltaText(delta)}
          </div>
        </div>
        <div className="score-hero-body">
          <h2>
            {grade === "A" || grade === "B"
              ? "Looking strong — here's the full picture."
              : `Your app is in ${GRADE_WORDS[grade].toLowerCase()} shape — ${urgentCount > 0 ? `${urgentCount} ${urgentCount === 1 ? "issue is" : "issues are"} doing most of the damage.` : "a few issues are doing most of the damage."}`}
          </h2>
          <p>{verdictForScore(result.score, urgentCount)}</p>
          <div className="hero-cta">
            {top && (
              <button className="btn btn-primary" onClick={() => onOpenIssue(top)}>
                Fix the top issue →
              </button>
            )}
            <button className="btn btn-ghost" onClick={() => onOpenSonar("Explain my score in plain language — what's dragging it down?")}>
              Ask Sonar to explain
            </button>
          </div>
          <div className="mini-stats">
            <div><span>Urgent</span><b style={{ color: dist.critical ? "var(--bad)" : "inherit" }}>{dist.critical ?? 0}</b></div>
            <div><span>High</span><b style={{ color: (dist.error ?? 0) ? "var(--high)" : "inherit" }}>{dist.error ?? 0}</b></div>
            <div><span>Medium</span><b>{dist.warning ?? 0}</b></div>
            <div><span>Low</span><b style={{ color: "var(--good)" }}>{dist.info ?? 0}</b></div>
          </div>
        </div>
      </section>

      <div className="section-head">
        <h3>Fix these first</h3>
        <button className="link" onClick={onShowAllIssues}>View all {result.finding_count} {copy.findings} →</button>
      </div>

      {ranked.length === 0 && (
        <div className="empty-panel">No {copy.findings} found — your code is clean. 🎉</div>
      )}
      {ranked.slice(0, 3).map((finding) => (
        <IssueCard key={finding.id} finding={finding} onOpen={onOpenIssue} />
      ))}

      <div className="two-col" style={{ marginTop: 38 }}>
        <div className="panel">
          <h3>Your score over time</h3>
          <div className="sub">Same code, same score — every scan, deterministic.</div>
          {spark ? (
            <>
              <div className="sparkline">
                {spark.map((s, i) => (
                  <div
                    key={i}
                    className={`sparkbar ${i < spark.length - 1 ? "old" : ""}`}
                    style={{ height: `${Math.max(8, ((s - 300) / 550) * 100)}%` }}
                    title={`Score ${s}`}
                  />
                ))}
              </div>
              <div className="spark-lbls">
                <span>{timeAgo(drift!.summary.baseline.scanned_at)}</span>
                <span>Today</span>
              </div>
              <p className="trend-note">
                <b>{deltaText(delta ?? 0)}.</b>{" "}
                {drift!.summary.resolved_count > 0 && `${drift!.summary.resolved_count} ${copy.findings} fixed. `}
                {drift!.summary.new_count > 0 && `${drift!.summary.new_count} new ${drift!.summary.new_count === 1 ? copy.finding : copy.findings} appeared.`}
              </p>
            </>
          ) : (
            <div className="empty-panel" style={{ marginTop: 8 }}>
              One scan so far. Re-scan after your next change and we&rsquo;ll chart your trend here.
            </div>
          )}
        </div>

        <div className="panel">
          <h3>Riskiest files</h3>
          <div className="sub">Where your {copy.findings} are concentrated.</div>
          {files.length === 0 && <div className="empty-panel">No files with {copy.findings}.</div>}
          {files.map((f) => (
            <button key={f.file_path} className="file-row" onClick={() => onShowAllIssues()}>
              <div className="file-ico">{(f.file_path.split(".").pop() ?? "?").slice(0, 3).toUpperCase()}</div>
              <div>
                <div className="fname">{f.file_path}</div>
                <div className="fsub">
                  {f.issueCount} {f.issueCount === 1 ? copy.finding : copy.findings} · {SEVERITY_LABEL[f.worst].toLowerCase()} priority
                </div>
              </div>
              <div className="fscore">
                <b>{f.issueCount}</b>
                <div className="riskbar">
                  <i
                    style={{
                      width: `${Math.round((f.risk / maxRisk) * 100)}%`,
                      background: f.worst === "critical" ? "var(--bad)" : f.worst === "error" ? "var(--high)" : "var(--ok)",
                    }}
                  />
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="section-head" style={{ marginTop: 38 }}>
        <h3>Health by area</h3>
        <button className="link" onClick={() => onOpenSonar("How is my score calculated?")}>How the score is calculated →</button>
      </div>
      <HealthByArea result={result} />

      <NerdsDetails>
        <div className="kv"><span>Scan id</span><span className="mono">{result.scan_id ?? "not persisted"}</span></div>
        <div className="kv"><span>Repository</span><span className="mono">{result.repository}</span></div>
        <div className="kv"><span>Scanned at</span><span className="mono">{result.scanned_at}</span></div>
        <div className="kv"><span>Fix-it points</span><span className="mono">{result.total_debt_points}</span></div>
        <div className="kv"><span>Checks ran</span><span className="mono">{Object.keys(result.findings_by_category).length} categories</span></div>
        <div style={{ marginTop: 12 }}>
          <pre>{rawJson({ grade: result.grade, category_scores: result.category_scores, severity_distribution: result.severity_distribution })}</pre>
        </div>
      </NerdsDetails>
    </div>
  );
}
