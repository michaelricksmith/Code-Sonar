import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  fetchAnalyzers,
  fetchDrift,
  fetchHealth,
  runScan,
} from "./api/analyzers";
import type {
  AnalyzerMetadata,
  DriftResult,
  Finding,
  FilterState,
  ScanResponse,
  SortState,
} from "./api/analyzers";
import { askSonar, fetchAskSonarStatus } from "./api/askSonar";
import type { AskSonarStatus, GroundedAnswerResponse } from "./api/askSonar";

import { AnalyzerMetadataPanel } from "./components/AnalyzerMetadataPanel";
import { DriftView } from "./components/DriftView";
import { FindingDetailDrawer } from "./components/FindingDetailDrawer";
import { FilterChips } from "./components/FilterChips";
import { ProjectDashboardPanel } from "./components/ProjectDashboardPanel";
import { RiskHotspots } from "./components/RiskHotspots";
import { SortableFindingsTable } from "./components/SortableFindingsTable";

const DEFAULT_REPO = "C:\\Users\\bookm\\.openclaw\\workspace\\code-sonar";
const EMPTY_FILTER: FilterState = {
  severities: new Set(),
  categories: new Set(),
  analyzers: new Set(),
  search: "",
};
const DEFAULT_SORT: SortState = { key: "severity", direction: "desc" };

type NavPage =
  | "overview"
  | "repositories"
  | "findings"
  | "risk"
  | "history"
  | "remediations"
  | "settings";

type NavGroup = {
  label: string;
  items: Array<{ page: NavPage; label: string; icon: string }>;
};

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { page: "overview", label: "Overview", icon: "OV" },
      { page: "repositories", label: "Repositories", icon: "RE" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { page: "findings", label: "Findings", icon: "FI" },
      { page: "risk", label: "Risk Map", icon: "RM" },
      { page: "history", label: "History", icon: "HI" },
    ],
  },
  {
    label: "Sonar",
    items: [{ page: "remediations", label: "Remediations", icon: "RX" }],
  },
  {
    label: "System",
    items: [{ page: "settings", label: "Engine & Rules", icon: "ER" }],
  },
];

const SEVERITY_WEIGHT = { info: 1, warning: 2, error: 4, critical: 8 } as const;

function matchesSearch(finding: Finding, search: string): boolean {
  if (!search.trim()) return true;
  const needle = search.trim().toLowerCase();
  return (
    finding.file_path.toLowerCase().includes(needle) ||
    (finding.symbol ?? "").toLowerCase().includes(needle) ||
    finding.evidence.toLowerCase().includes(needle) ||
    finding.message.toLowerCase().includes(needle) ||
    finding.rule_id.toLowerCase().includes(needle)
  );
}

function findingRisk(finding: Finding): number {
  return SEVERITY_WEIGHT[finding.severity] * finding.debt_points * finding.confidence;
}

function repoName(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.at(-1) ?? "Repository";
}

function scoreTone(score: number): string {
  if (score >= 760) return "good";
  if (score >= 650) return "fair";
  if (score >= 550) return "warn";
  return "bad";
}

function App() {
  const [activePage, setActivePage] = useState<NavPage>("overview");
  const [repoPath, setRepoPath] = useState(DEFAULT_REPO);
  const [health, setHealth] = useState("checking…");
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [analyzers, setAnalyzers] = useState<AnalyzerMetadata[]>([]);
  const [drift, setDrift] = useState<DriftResult | null>(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [driftError, setDriftError] = useState<string | null>(null);
  const [fileFilter, setFileFilter] = useState<string | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [askStatus, setAskStatus] = useState<AskSonarStatus | null>(null);
  const [question, setQuestion] = useState("What should I fix first, and why?");
  const [answer, setAnswer] = useState<GroundedAnswerResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((data) => setHealth(data.status))
      .catch(() => setHealth("unreachable"));
    fetchAskSonarStatus().then(setAskStatus).catch(() => setAskStatus(null));
  }, []);

  useEffect(() => {
    fetchAnalyzers().then(setAnalyzers).catch(() => setAnalyzers([]));
  }, [result]);

  const filtered = useMemo(() => {
    if (!result) return [] as Finding[];
    return result.findings.filter((finding) => {
      if (fileFilter !== null && finding.file_path !== fileFilter) return false;
      if (filter.severities.size > 0 && !filter.severities.has(finding.severity)) return false;
      if (filter.categories.size > 0 && !filter.categories.has(finding.category)) return false;
      if (filter.analyzers.size > 0 && !filter.analyzers.has(finding.analyzer)) return false;
      return matchesSearch(finding, filter.search);
    });
  }, [result, filter, fileFilter]);

  const priorities = useMemo(() => {
    if (!result) return [] as Finding[];
    return [...result.findings]
      .filter((finding) => !finding.file_path.replace(/\\/g, "/").includes("/tests/"))
      .sort((a, b) => findingRisk(b) - findingRisk(a))
      .slice(0, 5);
  }, [result]);

  async function onScan(): Promise<void> {
    setScanning(true);
    setError(null);
    setSelected(null);
    setAnswer(null);
    setDrift(null);
    setDriftError(null);
    try {
      const data = await runScan({ repo_path: repoPath });
      setResult(data);
      setActivePage("overview");
      fetchDrift(repoPath).then(setDrift).catch(() => setDrift(null));
    } catch (scanError) {
      setError(scanError instanceof Error ? scanError.message : String(scanError));
    } finally {
      setScanning(false);
    }
  }

  async function onShowDrift(): Promise<void> {
    setDriftLoading(true);
    setDriftError(null);
    try {
      setDrift(await fetchDrift(repoPath));
    } catch (driftLoadError) {
      const message = driftLoadError instanceof Error ? driftLoadError.message : String(driftLoadError);
      setDriftError(
        message.includes("HTTP 400") || message.includes("HTTP 404")
          ? "Run at least two scans of this repository to compute drift."
          : message,
      );
    } finally {
      setDriftLoading(false);
    }
  }

  async function onAskSonar(): Promise<void> {
    if (!result?.scan_id || !question.trim()) return;
    setAsking(true);
    setAskError(null);
    setAnswer(null);
    try {
      setAnswer(await askSonar({ scanId: result.scan_id, question: question.trim() }));
    } catch (askLoadError) {
      setAskError(askLoadError instanceof Error ? askLoadError.message : String(askLoadError));
    } finally {
      setAsking(false);
    }
  }

  function openFinding(finding: Finding): void {
    setSelected(finding);
  }

  function openFindingList(path?: string): void {
    setFileFilter(path ?? null);
    setActivePage("findings");
  }

  return (
    <div className={`cs-app ${assistantOpen ? "assistant-visible" : ""}`}>
      <aside className="cs-sidebar">
        <div>
          <div className="cs-brand">
            <div className="cs-logo"><span /></div>
            <div>
              <strong>Code Sonar</strong>
              <small>Code health intelligence</small>
            </div>
          </div>

          <div className="cs-sidebar-repo">
            <span className="cs-live-dot" />
            <div>
              <strong>{repoName(repoPath)}</strong>
              <small>{result ? `${result.score} · ${result.grade}` : "No baseline yet"}</small>
            </div>
          </div>

          {NAV_GROUPS.map((group) => (
            <div className="cs-nav-group" key={group.label}>
              <div className="cs-nav-label">{group.label}</div>
              {group.items.map((item) => {
                const badge = item.page === "findings" && result ? result.finding_count : null;
                return (
                  <button
                    type="button"
                    key={item.page}
                    className={`cs-nav-item ${activePage === item.page ? "active" : ""}`}
                    onClick={() => setActivePage(item.page)}
                  >
                    <span className="cs-nav-icon">{item.icon}</span>
                    <span>{item.label}</span>
                    {badge !== null && <em>{badge}</em>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <div className="cs-sidebar-bottom">
          <button type="button" className="cs-sonar-launch" onClick={() => setAssistantOpen(true)}>
            <span className="cs-sonar-pulse" />
            <span>
              <strong>Ask Sonar</strong>
              <small>{askStatus?.configured ? "AI ready" : "Deterministic guidance"}</small>
            </span>
            <b>⌘</b>
          </button>
          <div className="cs-engine-state">
            <span className={health === "ok" ? "online" : "offline"} />
            Engine {health === "ok" ? "online" : health}
          </div>
        </div>
      </aside>

      <section className="cs-workspace">
        <header className="cs-topbar">
          <div>
            <div className="cs-breadcrumb">Workspace / {repoName(repoPath)}</div>
            <div className="cs-topbar-title">{pageTitle(activePage)}</div>
          </div>
          <div className="cs-topbar-actions">
            {result && (
              <div className={`cs-score-chip ${scoreTone(result.score)}`}>
                <span>{result.score}</span>
                <small>{result.grade}</small>
              </div>
            )}
            <button type="button" className="cs-button ghost" onClick={() => setAssistantOpen(true)}>
              Ask Sonar
            </button>
            <button type="button" className="cs-button primary" onClick={onScan} disabled={scanning || !repoPath.trim()}>
              {scanning ? "Scanning…" : "Run scan"}
            </button>
          </div>
        </header>

        <main className="cs-content">
          {error && <Notice tone="danger" title="Scan failed">{error}</Notice>}

          {activePage === "overview" && (
            <Overview
              result={result}
              repoPath={repoPath}
              setRepoPath={setRepoPath}
              scanning={scanning}
              drift={drift}
              priorities={priorities}
              onScan={onScan}
              onOpenFinding={openFinding}
              onOpenFindings={openFindingList}
              onOpenAssistant={() => setAssistantOpen(true)}
            />
          )}

          {activePage === "repositories" && (
            <Page title="Repositories" subtitle="Connect, monitor, and scan repositories from one place.">
              <div className="cs-repository-path-card">
                <div>
                  <span className="cs-kicker">Local workspace</span>
                  <h3>Scan a local repository</h3>
                  <p>Use a local checkout for development or install the GitHub App below for managed monitoring.</p>
                </div>
                <div className="cs-path-row">
                  <input value={repoPath} onChange={(event) => setRepoPath(event.target.value)} spellCheck={false} />
                  <button className="cs-button primary" onClick={onScan} disabled={scanning || !repoPath.trim()}>
                    {scanning ? "Scanning…" : "Scan repository"}
                  </button>
                </div>
              </div>
              <div className="cs-legacy-surface"><ProjectDashboardPanel /></div>
            </Page>
          )}

          {activePage === "findings" && (
            <Page title="Findings" subtitle="Your prioritized technical-debt work queue.">
              {!result ? (
                <NoBaseline onScan={onScan} scanning={scanning} />
              ) : (
                <div className="cs-inbox-card">
                  <div className="cs-inbox-head">
                    <div>
                      <span className="cs-kicker">Issue inbox</span>
                      <h3>{filtered.length} findings</h3>
                    </div>
                    {fileFilter && <button className="cs-link-button" onClick={() => setFileFilter(null)}>Clear file filter</button>}
                  </div>
                  <FilterChips findings={result.findings} analyzers={analyzers} filter={filter} onChange={setFilter} />
                  <div className="cs-table-wrap">
                    <SortableFindingsTable findings={filtered} onSelect={openFinding} sort={sort} onSortChange={setSort} />
                  </div>
                </div>
              )}
            </Page>
          )}

          {activePage === "risk" && (
            <Page title="Risk Map" subtitle="Where debt and analyzer agreement are concentrated.">
              {result?.top_hotspots?.length ? (
                <div className="cs-risk-surface">
                  <RiskHotspots
                    hotspots={result.top_hotspots}
                    hotspotSummary={{
                      total_files: result.top_hotspots.length,
                      files_with_findings: new Set(result.findings.map((finding) => finding.file_path)).size,
                      total_findings: result.finding_count,
                      total_debt: result.total_debt_points,
                    }}
                    findings={result.findings}
                    onFilterByFile={openFindingList}
                    activeFileFilter={fileFilter}
                  />
                </div>
              ) : <NoBaseline onScan={onScan} scanning={scanning} />}
            </Page>
          )}

          {activePage === "history" && (
            <Page title="History" subtitle="See whether the codebase is getting healthier or accumulating debt.">
              <div className="cs-history-card">
                <div className="cs-history-head">
                  <div>
                    <span className="cs-kicker">Scan-to-scan movement</span>
                    <h3>Drift analysis</h3>
                    <p>New, resolved, improved, and worsened findings against the previous baseline.</p>
                  </div>
                  <button className="cs-button primary" onClick={onShowDrift} disabled={!result || driftLoading}>
                    {driftLoading ? "Comparing…" : "Compare previous scan"}
                  </button>
                </div>
                {driftError && <Notice tone="warning" title="Drift unavailable">{driftError}</Notice>}
                {drift ? <DriftView drift={drift} /> : <div className="cs-empty-panel">Run a second scan to unlock change intelligence.</div>}
              </div>
            </Page>
          )}

          {activePage === "remediations" && (
            <Page title="Remediations" subtitle="Move from finding to validated fix without giving up score authority.">
              {!result ? <NoBaseline onScan={onScan} scanning={scanning} /> : (
                <div className="cs-remediation-layout">
                  <section className="cs-flow-card">
                    <span className="cs-kicker">Agent execution loop</span>
                    <h3>Review → approve → execute → test → rescan</h3>
                    <div className="cs-flow-steps">
                      {[
                        ["01", "Choose finding", "Select a production finding with clear evidence."],
                        ["02", "Review plan", "Sonar generates the bounded remediation plan."],
                        ["03", "Approve execution", "No code changes occur without explicit approval."],
                        ["04", "Validate outcome", "Tests and a deterministic rescan measure the result."],
                      ].map(([n, title, copy]) => (
                        <div key={n}><b>{n}</b><span><strong>{title}</strong><small>{copy}</small></span></div>
                      ))}
                    </div>
                  </section>
                  <section className="cs-priority-card">
                    <div className="cs-card-head"><div><span className="cs-kicker">Ready to investigate</span><h3>Highest-impact findings</h3></div></div>
                    <PriorityList findings={priorities} onOpenFinding={openFinding} onAsk={() => setAssistantOpen(true)} />
                  </section>
                </div>
              )}
            </Page>
          )}

          {activePage === "settings" && (
            <Page title="Engine & Rules" subtitle="Advanced deterministic analysis configuration and runtime visibility.">
              <div className="cs-settings-summary">
                <Metric label="API" value={health} detail="runtime" />
                <Metric label="Analyzers" value={String(analyzers.length)} detail="deterministic rules" />
                <Metric label="Score authority" value="Code Sonar" detail="ML remains advisory" />
              </div>
              <div className="cs-legacy-surface"><AnalyzerMetadataPanel refreshKey={result ? result.finding_count : undefined} /></div>
            </Page>
          )}
        </main>
      </section>

      <AssistantPanel
        open={assistantOpen}
        status={askStatus}
        result={result}
        question={question}
        answer={answer}
        asking={asking}
        error={askError}
        setQuestion={setQuestion}
        onAsk={onAskSonar}
        onClose={() => setAssistantOpen(false)}
      />

      <FindingDetailDrawer
        finding={selected}
        scanId={result?.scan_id ?? null}
        currentScore={result?.score ?? null}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}

function Overview({
  result,
  repoPath,
  setRepoPath,
  scanning,
  drift,
  priorities,
  onScan,
  onOpenFinding,
  onOpenFindings,
  onOpenAssistant,
}: {
  result: ScanResponse | null;
  repoPath: string;
  setRepoPath: (value: string) => void;
  scanning: boolean;
  drift: DriftResult | null;
  priorities: Finding[];
  onScan: () => void;
  onOpenFinding: (finding: Finding) => void;
  onOpenFindings: (path?: string) => void;
  onOpenAssistant: () => void;
}) {
  if (!result) {
    return (
      <div className="cs-onboarding">
        <div className="cs-onboarding-copy">
          <span className="cs-kicker">Your codebase credit report</span>
          <h1>Know the health of your code before technical debt compounds.</h1>
          <p>Attach a repository to establish a deterministic baseline. Code Sonar will score it, rank the highest-risk files, and explain what to fix first.</p>
          <div className="cs-onboarding-input">
            <input value={repoPath} onChange={(event) => setRepoPath(event.target.value)} spellCheck={false} />
            <button className="cs-button primary large" onClick={onScan} disabled={scanning || !repoPath.trim()}>
              {scanning ? "Building baseline…" : "Create baseline"}
            </button>
          </div>
          <div className="cs-trust-row"><span>Deterministic scoring</span><span>Evidence-backed findings</span><span>No silent AI score changes</span></div>
        </div>
        <div className="cs-preview-score"><div><strong>—</strong><small>CODE HEALTH</small></div><p>Your score will appear here after the first scan.</p></div>
      </div>
    );
  }

  const sourceBreakdown = result.findings_source_breakdown ?? { source: 0, test: 0, fixture: 0 };
  const scoreDelta = drift?.summary.score_delta ?? null;
  const categories = Object.entries(result.category_scores).sort((a, b) => a[1] - b[1]);

  return (
    <div className="cs-overview">
      <section className="cs-score-hero">
        <div className={`cs-score-orbit ${scoreTone(result.score)}`} style={{ "--score-progress": `${Math.max(0, Math.min(100, ((result.score - 300) / 550) * 100))}%` } as React.CSSProperties}>
          <div><strong>{result.score}</strong><span>850</span><small>CODE HEALTH</small></div>
        </div>
        <div className="cs-score-copy">
          <span className="cs-kicker">Current baseline</span>
          <div className={`cs-grade-line ${scoreTone(result.score)}`}><strong>{result.grade}</strong><span>{gradeLabel(result.grade)}</span></div>
          <p>{scoreSummary(result.score, result.severity_distribution.critical)}</p>
          <div className="cs-score-meta">
            {scoreDelta !== null && <span className={scoreDelta >= 0 ? "positive" : "negative"}>{scoreDelta >= 0 ? "↑" : "↓"} {Math.abs(scoreDelta)} since previous scan</span>}
            <span>Scanned {new Date(result.scanned_at).toLocaleString()}</span>
          </div>
        </div>
        <div className="cs-hero-actions">
          <button className="cs-button primary" onClick={onOpenAssistant}>Ask Sonar what this means</button>
          <button className="cs-button ghost" onClick={() => onOpenFindings()}>View all findings</button>
        </div>
      </section>

      <section className="cs-metric-strip">
        <Metric label="Critical risks" value={String(result.severity_distribution.critical)} detail="needs attention" tone={result.severity_distribution.critical ? "danger" : "normal"} />
        <Metric label="Technical debt" value={String(result.total_debt_points)} detail="debt points" />
        <Metric label="Findings" value={String(result.finding_count)} detail={`${sourceBreakdown.source} source · ${sourceBreakdown.test} test`} />
        <Metric label="Files at risk" value={String(new Set(result.findings.map((finding) => finding.file_path)).size)} detail="with findings" />
      </section>

      <div className="cs-overview-grid">
        <section className="cs-priority-card">
          <div className="cs-card-head">
            <div><span className="cs-kicker">What to fix first</span><h3>Top priorities</h3></div>
            <button className="cs-link-button" onClick={() => onOpenFindings()}>View all {result.finding_count} →</button>
          </div>
          <PriorityList findings={priorities} onOpenFinding={onOpenFinding} onAsk={onOpenAssistant} />
        </section>

        <section className="cs-category-card">
          <div className="cs-card-head"><div><span className="cs-kicker">Score drivers</span><h3>Category health</h3></div></div>
          <div className="cs-category-stack">
            {categories.map(([category, score]) => (
              <div className="cs-category-row" key={category}>
                <div><span>{category}</span><strong>{score}</strong></div>
                <div className="cs-category-bar"><span style={{ width: `${Math.max(0, Math.min(100, ((score - 300) / 550) * 100))}%` }} /></div>
                <small>{result.findings_by_category[category as keyof typeof result.findings_by_category]} findings</small>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function PriorityList({ findings, onOpenFinding, onAsk }: { findings: Finding[]; onOpenFinding: (finding: Finding) => void; onAsk: () => void }) {
  if (findings.length === 0) return <div className="cs-empty-panel">No priority findings in the current baseline.</div>;
  return (
    <div className="cs-priority-list">
      {findings.map((finding, index) => (
        <div className="cs-priority-item" key={finding.id}>
          <div className="cs-priority-rank">{String(index + 1).padStart(2, "0")}</div>
          <div className="cs-priority-main">
            <div className="cs-priority-title"><strong>{compactPath(finding.file_path)}</strong><span className={`cs-severity ${finding.severity}`}>{finding.severity}</span></div>
            <p>{finding.message}</p>
            <div className="cs-priority-meta"><span>{finding.analyzer}</span><span>{finding.debt_points} debt points</span><span>{finding.category}</span></div>
          </div>
          <div className="cs-priority-actions">
            <button onClick={() => onOpenFinding(finding)}>Investigate</button>
            <button className="accent" onClick={() => { onOpenFinding(finding); onAsk(); }}>Fix with Sonar</button>
          </div>
        </div>
      ))}
    </div>
  );
}

function AssistantPanel({
  open,
  status,
  result,
  question,
  answer,
  asking,
  error,
  setQuestion,
  onAsk,
  onClose,
}: {
  open: boolean;
  status: AskSonarStatus | null;
  result: ScanResponse | null;
  question: string;
  answer: GroundedAnswerResponse | null;
  asking: boolean;
  error: string | null;
  setQuestion: (value: string) => void;
  onAsk: () => void;
  onClose: () => void;
}) {
  return (
    <aside className={`cs-assistant ${open ? "open" : ""}`}>
      <div className="cs-assistant-head">
        <div className="cs-assistant-brand"><span className="cs-sonar-pulse" /><div><strong>Ask Sonar</strong><small>{status?.configured ? `${status.provider} · grounded` : "Deterministic guidance"}</small></div></div>
        <button onClick={onClose}>×</button>
      </div>
      <div className="cs-assistant-context">
        <span>Context</span>
        <strong>{result ? `${repoName(result.repository)} · ${result.score} ${result.grade}` : "No active baseline"}</strong>
        <small>{result?.scan_id ? `Scan ${result.scan_id.slice(0, 8)}` : "Run a scan to ground answers in repository evidence."}</small>
      </div>
      <div className="cs-assistant-body">
        <div className="cs-assistant-welcome">
          <span className="cs-kicker">Repository-aware copilot</span>
          <h3>Ask about the score, risks, or next fix.</h3>
          <p>Sonar can explain deterministic findings and prepare remediation plans. It cannot silently change the score.</p>
        </div>
        <div className="cs-quick-prompts">
          {["Why is my score this value?", "What should I fix first?", "Which file is the biggest risk?"].map((prompt) => (
            <button key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>
          ))}
        </div>
        {answer && <div className="cs-answer"><span>SONAR</span><p>{answer.answer.answer}</p><small>{answer.answer.used_sources.length} grounded sources · score unchanged</small></div>}
        {error && <Notice tone="warning" title="Ask Sonar unavailable">{error}</Notice>}
      </div>
      <div className="cs-assistant-compose">
        <textarea rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask Sonar about this repository…" />
        <div><small>{status?.configured ? "AI provider connected" : "Provider not configured"}</small><button className="cs-button primary" onClick={onAsk} disabled={!result?.scan_id || asking || !question.trim()}>{asking ? "Thinking…" : "Ask"}</button></div>
      </div>
    </aside>
  );
}

function Page({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return <div className="cs-page"><div className="cs-page-head"><span className="cs-kicker">Code Sonar</span><h1>{title}</h1><p>{subtitle}</p></div>{children}</div>;
}

function Metric({ label, value, detail, tone = "normal" }: { label: string; value: string; detail: string; tone?: "normal" | "danger" }) {
  return <div className={`cs-metric ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function NoBaseline({ onScan, scanning }: { onScan: () => void; scanning: boolean }) {
  return <div className="cs-no-baseline"><div className="cs-logo large"><span /></div><h2>No baseline yet</h2><p>Run a deterministic scan to unlock this view.</p><button className="cs-button primary" onClick={onScan} disabled={scanning}>{scanning ? "Scanning…" : "Run first scan"}</button></div>;
}

function Notice({ tone, title, children }: { tone: "danger" | "warning"; title: string; children: ReactNode }) {
  return <div className={`cs-notice ${tone}`}><strong>{title}</strong><span>{children}</span></div>;
}

function pageTitle(page: NavPage): string {
  return {
    overview: "Code health overview",
    repositories: "Repositories",
    findings: "Findings",
    risk: "Risk map",
    history: "History",
    remediations: "Remediations",
    settings: "Engine & rules",
  }[page];
}

function compactPath(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts.length > 4 ? `…/${parts.slice(-4).join("/")}` : normalized;
}

function gradeLabel(grade: string): string {
  return ({ A: "Excellent", B: "Healthy", C: "Watch", D: "At risk", F: "High risk" } as Record<string, string>)[grade] ?? "Code health";
}

function scoreSummary(score: number, critical: number): string {
  if (critical > 0) return `${critical} critical finding${critical === 1 ? "" : "s"} require attention. Focus on concentrated production risk before broad cleanup.`;
  if (score >= 760) return "The repository is in strong shape. Protect the baseline and address emerging debt before it compounds.";
  if (score >= 650) return "The codebase is generally healthy, with a few concentrated areas that should be addressed next.";
  if (score >= 550) return "Technical debt is materially affecting maintainability. Prioritize the highest-risk files first.";
  return "Debt is significantly affecting code health. Use the priority queue to attack the highest-impact production risks first.";
}

export default App;
