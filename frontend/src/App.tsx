import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { fetchAnalyzers, fetchDrift, fetchHealth, runScan } from "./api/analyzers";
import type { AnalyzerMetadata, DriftResult, Finding, FilterState, ScanResponse, SortState } from "./api/analyzers";
import { askSonar, fetchAskSonarStatus } from "./api/askSonar";
import type { AskSonarStatus, GroundedAnswerResponse } from "./api/askSonar";
import { AnalyzerMetadataPanel } from "./components/AnalyzerMetadataPanel";
import { DriftView } from "./components/DriftView";
import { FindingDetailDrawer } from "./components/FindingDetailDrawer";
import { FilterChips } from "./components/FilterChips";
import { ProjectDashboardPanel } from "./components/ProjectDashboardPanel";
import { RepositoryGateway } from "./components/RepositoryGateway";
import { RiskHotspots } from "./components/RiskHotspots";
import { SortableFindingsTable } from "./components/SortableFindingsTable";

const DEFAULT_REPO = "C:\\Users\\bookm\\.openclaw\\workspace\\code-sonar";
const EMPTY_FILTER: FilterState = { severities: new Set(), categories: new Set(), analyzers: new Set(), search: "" };
const DEFAULT_SORT: SortState = { key: "severity", direction: "desc" };
const SEVERITY_WEIGHT = { info: 1, warning: 2, error: 4, critical: 8 } as const;

type PageId = "overview" | "repositories" | "findings" | "risk" | "history" | "remediations" | "integrations" | "settings";

const NAV = [
  ["Workspace", [["overview", "Overview", "⌂"], ["repositories", "Repositories", "◇"]]],
  ["Intelligence", [["findings", "Findings", "≡"], ["risk", "Risk Map", "◎"], ["history", "History", "↗"]]],
  ["Sonar", [["remediations", "Remediations", "✦"]]],
  ["System", [["integrations", "Integrations", "⌁"], ["settings", "Engine & Rules", "⚙"]]],
] as const;

function repoName(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : "Repository";
}

function scoreTone(score: number): string {
  if (score >= 760) return "good";
  if (score >= 650) return "fair";
  if (score >= 550) return "warn";
  return "bad";
}

function risk(finding: Finding): number {
  return SEVERITY_WEIGHT[finding.severity] * finding.debt_points * finding.confidence;
}

function matchesSearch(finding: Finding, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return [finding.file_path, finding.symbol ?? "", finding.evidence, finding.message, finding.rule_id]
    .some((value) => value.toLowerCase().includes(needle));
}

function App() {
  const [page, setPage] = useState<PageId>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [repoPath, setRepoPath] = useState(DEFAULT_REPO);
  const [health, setHealth] = useState("checking…");
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [analyzers, setAnalyzers] = useState<AnalyzerMetadata[]>([]);
  const [fileFilter, setFileFilter] = useState<string | null>(null);
  const [drift, setDrift] = useState<DriftResult | null>(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [driftError, setDriftError] = useState<string | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [askStatus, setAskStatus] = useState<AskSonarStatus | null>(null);
  const [question, setQuestion] = useState("What should I fix first, and why?");
  const [answer, setAnswer] = useState<GroundedAnswerResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth().then((data) => setHealth(data.status)).catch(() => setHealth("unreachable"));
    fetchAskSonarStatus().then(setAskStatus).catch(() => setAskStatus(null));
  }, []);

  useEffect(() => {
    fetchAnalyzers().then(setAnalyzers).catch(() => setAnalyzers([]));
  }, [result]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavOpen]);

  const filtered = useMemo(() => {
    if (!result) return [];
    return result.findings.filter((finding) => {
      if (fileFilter !== null && finding.file_path !== fileFilter) return false;
      if (filter.severities.size > 0 && !filter.severities.has(finding.severity)) return false;
      if (filter.categories.size > 0 && !filter.categories.has(finding.category)) return false;
      if (filter.analyzers.size > 0 && !filter.analyzers.has(finding.analyzer)) return false;
      return matchesSearch(finding, filter.search);
    });
  }, [result, filter, fileFilter]);

  const priorities = useMemo(() => {
    if (!result) return [];
    return [...result.findings]
      .filter((finding) => !finding.file_path.replace(/\\/g, "/").includes("/tests/"))
      .sort((a, b) => risk(b) - risk(a))
      .slice(0, 5);
  }, [result]);

  async function scan(): Promise<void> {
    setScanning(true);
    setError(null);
    setSelected(null);
    setAnswer(null);
    setDrift(null);
    setDriftError(null);
    try {
      const data = await runScan({ repo_path: repoPath });
      setResult(data);
      setPage("overview");
      fetchDrift(repoPath).then(setDrift).catch(() => setDrift(null));
    } catch (scanError) {
      setError(scanError instanceof Error ? scanError.message : String(scanError));
    } finally {
      setScanning(false);
    }
  }

  async function compareDrift(): Promise<void> {
    setDriftLoading(true);
    setDriftError(null);
    try {
      setDrift(await fetchDrift(repoPath));
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : String(loadError);
      setDriftError(message.includes("HTTP 400") || message.includes("HTTP 404") ? "Run at least two scans to compute drift." : message);
    } finally {
      setDriftLoading(false);
    }
  }

  async function ask(): Promise<void> {
    if (!result?.scan_id || !question.trim()) return;
    setAsking(true);
    setAskError(null);
    setAnswer(null);
    try {
      setAnswer(await askSonar({ scanId: result.scan_id, question: question.trim() }));
    } catch (loadError) {
      setAskError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setAsking(false);
    }
  }

  function showFindings(path?: string | null): void {
    setFileFilter(path ?? null);
    setPage("findings");
  }

  return (
    <div className={`cs-app ${assistantOpen ? "sonar-open" : ""}`}>
      {mobileNavOpen ? <button className="cs-nav-backdrop" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} /> : null}
      <aside id="code-sonar-navigation" className={`cs-sidebar ${mobileNavOpen ? "mobile-open" : ""}`} aria-label="Primary navigation">
        <div>
          <div className="cs-brand"><div className="cs-logo"><span /></div><div><strong>Code Sonar</strong><small>Code health intelligence</small></div></div>
          <div className="cs-sidebar-repo"><span className="cs-live-dot" /><div><strong>{repoName(repoPath)}</strong><small>{result ? `${result.score} · ${result.grade}` : "No baseline yet"}</small></div></div>
          {NAV.map(([group, items]) => (
            <div className="cs-nav-group" key={group}>
              <div className="cs-nav-label">{group}</div>
              {items.map(([id, label, icon]) => (
                <button key={id} className={`cs-nav-item ${page === id ? "active" : ""}`} onClick={() => { setPage(id as PageId); setMobileNavOpen(false); }}>
                  <span className="cs-nav-icon">{icon}</span><span>{label}</span>{id === "findings" && result ? <em>{result.finding_count}</em> : null}
                </button>
              ))}
            </div>
          ))}
        </div>
        <div className="cs-sidebar-bottom">
          <button className="cs-sonar-launch" onClick={() => setAssistantOpen(true)}><span className="cs-sonar-pulse" /><span><strong>Ask Sonar</strong><small>{askStatus?.configured ? "AI ready" : "Deterministic guidance"}</small></span><b>⌘</b></button>
          <div className="cs-engine-state"><span className={health === "ok" ? "online" : "offline"} />Engine {health === "ok" ? "online" : health}</div>
        </div>
      </aside>

      <section className="cs-workspace">
        <div className="cs-telemetry"><span><i /> LIVE ANALYSIS</span><span>DETERMINISTIC ENGINE</span><span>{result ? `${result.finding_count} SIGNALS` : "AWAITING BASELINE"}</span><span>ML ADVISORY ONLY</span></div>
        <header className="cs-topbar">
          <button className="cs-menu-button" type="button" aria-label="Open navigation" aria-controls="code-sonar-navigation" aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen(true)}><span /><span /><span /></button>
          <div><div className="cs-breadcrumb">Workspace / {repoName(repoPath)}</div><div className="cs-topbar-title">{pageTitle(page)}</div></div>
          <div className="cs-topbar-actions">
            {result ? <div className={`cs-score-chip ${scoreTone(result.score)}`}><span>{result.score}</span><small>{result.grade}</small></div> : null}
            <button className="cs-button ghost" onClick={() => setAssistantOpen(true)}>Ask Sonar</button>
            <button className="cs-button primary" onClick={scan} disabled={scanning || !repoPath.trim()}>{scanning ? "Scanning…" : "Run scan"}</button>
          </div>
        </header>

        <main className="cs-content">
          {error ? <Notice tone="danger" title="Scan failed">{error}</Notice> : null}

          {page === "overview" ? <Overview result={result} repoPath={repoPath} setRepoPath={setRepoPath} scanning={scanning} drift={drift} priorities={priorities} scan={scan} select={setSelected} showFindings={showFindings} openSonar={() => setAssistantOpen(true)} openRepositories={() => setPage("repositories")} /> : null}

          {page === "repositories" ? <Page title="Repositories" subtitle="Connect, monitor, and scan repositories from one place."><div className="cs-repository-path-card"><span className="cs-kicker">Local workspace</span><h3>Scan a local repository</h3><p>Use a local checkout for development or the GitHub App below for managed monitoring.</p><div className="cs-path-row"><input value={repoPath} onChange={(e) => setRepoPath(e.target.value)} spellCheck={false} /><button className="cs-button primary" onClick={scan} disabled={scanning || !repoPath.trim()}>{scanning ? "Scanning…" : "Scan repository"}</button></div></div><div className="cs-legacy-surface"><ProjectDashboardPanel /></div></Page> : null}

          {page === "findings" ? <Page title="Findings" subtitle="Your prioritized technical-debt work queue.">{result ? <div className="cs-inbox-card"><div className="cs-inbox-head"><div><span className="cs-kicker">Issue inbox</span><h3>{filtered.length} findings</h3></div>{fileFilter ? <button className="cs-link-button" onClick={() => setFileFilter(null)}>Clear file filter</button> : null}</div><FilterChips findings={result.findings} analyzers={analyzers} filter={filter} onChange={setFilter} /><div className="cs-table-wrap"><SortableFindingsTable findings={filtered} onSelect={setSelected} sort={sort} onSortChange={setSort} /></div></div> : <NoBaseline scan={scan} scanning={scanning} />}</Page> : null}

          {page === "risk" ? <Page title="Risk Map" subtitle="Where debt and analyzer agreement are concentrated.">{result?.top_hotspots?.length ? <div className="cs-risk-surface"><RiskHotspots hotspots={result.top_hotspots} hotspotSummary={{ total_files: result.top_hotspots.length, files_with_findings: new Set(result.findings.map((finding) => finding.file_path)).size, total_findings: result.finding_count, total_debt: result.total_debt_points }} findings={result.findings} onFilterByFile={showFindings} activeFileFilter={fileFilter} /></div> : <NoBaseline scan={scan} scanning={scanning} />}</Page> : null}

          {page === "history" ? <Page title="History" subtitle="See whether the codebase is getting healthier or accumulating debt."><div className="cs-history-card"><div className="cs-history-head"><div><span className="cs-kicker">Scan-to-scan movement</span><h3>Drift analysis</h3><p>New, resolved, improved, and worsened findings against the previous baseline.</p></div><button className="cs-button primary" onClick={compareDrift} disabled={!result || driftLoading}>{driftLoading ? "Comparing…" : "Compare previous scan"}</button></div>{driftError ? <Notice tone="warning" title="Drift unavailable">{driftError}</Notice> : null}{drift ? <DriftView drift={drift} /> : <div className="cs-empty-panel">Run a second scan to unlock change intelligence.</div>}</div></Page> : null}

          {page === "remediations" ? <Page title="Remediations" subtitle="Move from finding to validated fix without giving up score authority.">{result ? <div className="cs-remediation-layout"><section className="cs-flow-card"><span className="cs-kicker">Agent execution loop</span><h3>Review → approve → execute → test → rescan</h3><div className="cs-flow-steps">{[["01","Choose finding","Select a production finding with clear evidence."],["02","Review plan","Sonar generates a bounded remediation plan."],["03","Approve execution","No code changes occur without explicit approval."],["04","Validate outcome","Tests and a deterministic rescan measure the result."]].map(([n,t,c]) => <div key={n}><b>{n}</b><span><strong>{t}</strong><small>{c}</small></span></div>)}</div></section><section className="cs-priority-card"><div className="cs-card-head"><div><span className="cs-kicker">Ready to investigate</span><h3>Highest-impact findings</h3></div></div><PriorityList findings={priorities} select={setSelected} openSonar={() => setAssistantOpen(true)} /></section></div> : <NoBaseline scan={scan} scanning={scanning} />}</Page> : null}

          {page === "integrations" ? <Page title="Integrations" subtitle="Connect source control and keep repository intelligence current."><div className="cs-integration-grid"><section className="cs-integration-card featured"><div className="cs-integration-mark">GH</div><div><span className="cs-kicker">Source control</span><h3>GitHub App</h3><p>Managed repository access, default-branch monitoring, and deterministic scans on pushes and merged pull requests.</p><div className="cs-integration-status"><i className={health === "ok" ? "online" : ""} /> Configuration is managed securely by the backend</div></div></section><section className="cs-integration-card"><div className="cs-integration-mark local">//</div><div><span className="cs-kicker">Developer workspace</span><h3>Local repositories</h3><p>Scan a checkout directly during development without changing the repository.</p><button className="cs-button ghost" onClick={() => setPage("repositories")}>Manage repositories</button></div></section></div><div className="cs-legacy-surface"><ProjectDashboardPanel /></div></Page> : null}

          {page === "settings" ? <Page title="Engine & Rules" subtitle="Advanced deterministic analysis configuration and runtime visibility."><div className="cs-settings-summary"><Metric label="API" value={health} detail="runtime" /><Metric label="Analyzers" value={String(analyzers.length)} detail="deterministic rules" /><Metric label="Score authority" value="Code Sonar" detail="ML remains advisory" /></div><div className="cs-legacy-surface"><AnalyzerMetadataPanel refreshKey={result ? result.finding_count : undefined} /></div></Page> : null}
        </main>
      </section>

      {!assistantOpen ? <button className="cs-sonar-rail" onClick={() => setAssistantOpen(true)} aria-label="Open Ask Sonar"><span className="cs-sonar-pulse" /><b>ASK SONAR</b><small>⌘ K</small></button> : null}
      <Assistant open={assistantOpen} status={askStatus} result={result} question={question} answer={answer} asking={asking} error={askError} setQuestion={setQuestion} ask={ask} close={() => setAssistantOpen(false)} />
      <FindingDetailDrawer finding={selected} scanId={result?.scan_id ?? null} currentScore={result?.score ?? null} onClose={() => setSelected(null)} />
    </div>
  );
}

function Overview({ result, repoPath, setRepoPath, scanning, drift, priorities, scan, select, showFindings, openSonar, openRepositories }: { result: ScanResponse | null; repoPath: string; setRepoPath: (value: string) => void; scanning: boolean; drift: DriftResult | null; priorities: Finding[]; scan: () => void; select: (finding: Finding) => void; showFindings: (path?: string | null) => void; openSonar: () => void; openRepositories: () => void }) {
  if (!result) return <RepositoryGateway repoPath={repoPath} onRepoPathChange={setRepoPath} onLocalScan={scan} onOpenGitHub={openRepositories} scanning={scanning} />;

  const breakdown = result.findings_source_breakdown ?? { source: 0, test: 0, fixture: 0 };
  const delta = drift?.summary.score_delta ?? null;
  const categories = Object.entries(result.category_scores).sort((a, b) => a[1] - b[1]);
  const progress = Math.max(0, Math.min(100, ((result.score - 300) / 550) * 100));
  const ringStyle = { "--score-progress": `${progress}%` } as CSSProperties;

  return <div className="cs-overview">
    <section className="cs-command-center">
      <div className="cs-command-grid">
        <div className="cs-score-station">
          <div className="cs-score-scale"><span>300</span><span>Code Sonar score</span><span>850</span></div>
          <div className={`cs-score-orbit ${scoreTone(result.score)}`} style={ringStyle}>
            <div><strong>{result.score}</strong><span>/ 850</span><small>DETERMINISTIC SCORE</small></div>
          </div>
          <div className={`cs-grade-badge ${scoreTone(result.score)}`}><strong>{result.grade}</strong><span>{gradeLabel(result.grade)}</span></div>
        </div>
        <div className="cs-score-copy">
          <span className="cs-kicker">Current repository baseline</span>
          <h1>{repoName(result.repository)} code health</h1>
          <p>{scoreSummary(result.score, result.severity_distribution.critical)}</p>
          <div className="cs-score-meta">
            {delta !== null ? <span className={delta >= 0 ? "positive" : "negative"}>{delta >= 0 ? "↑" : "↓"} {Math.abs(delta)} since previous scan</span> : <span>First recorded baseline</span>}
            <span>Scanned {new Date(result.scanned_at).toLocaleString()}</span>
          </div>
          <div className="cs-hero-actions"><button className="cs-button primary" onClick={openSonar}>Ask Sonar what this means</button><button className="cs-button ghost" onClick={() => showFindings()}>View all findings</button></div>
        </div>
        <div className="cs-signal-stack" aria-label="Baseline signal summary">
          <div><span>Critical</span><strong>{result.severity_distribution.critical}</strong></div>
          <div><span>Errors</span><strong>{result.severity_distribution.error}</strong></div>
          <div><span>Warnings</span><strong>{result.severity_distribution.warning}</strong></div>
          <div><span>Information</span><strong>{result.severity_distribution.info}</strong></div>
        </div>
      </div>
      <div className="cs-scan-ledger">
        <span><small>Repository</small><strong>{compactPath(result.repository)}</strong></span>
        <span><small>Scan ID</small><strong>{result.scan_id.slice(0, 12)}</strong></span>
        <span><small>Findings analyzed</small><strong>{result.finding_count}</strong></span>
        <span><small>Debt measured</small><strong>{result.total_debt_points} points</strong></span>
      </div>
    </section>
    <section className="cs-metric-strip"><Metric label="Critical risks" value={String(result.severity_distribution.critical)} detail="needs attention" tone={result.severity_distribution.critical ? "danger" : "normal"} /><Metric label="Technical debt" value={String(result.total_debt_points)} detail="debt points" /><Metric label="Findings" value={String(result.finding_count)} detail={`${breakdown.source} source · ${breakdown.test} test · ${breakdown.fixture} fixture`} /><Metric label="Files at risk" value={String(new Set(result.findings.map((finding) => finding.file_path)).size)} detail="with findings" /></section>
    <div className="cs-overview-grid"><section className="cs-priority-card"><div className="cs-card-head"><div><span className="cs-kicker">What to fix first</span><h3>Top priorities</h3></div><button className="cs-link-button" onClick={() => showFindings()}>View all {result.finding_count} →</button></div><PriorityList findings={priorities} select={select} openSonar={openSonar} /></section><section className="cs-category-card"><div className="cs-card-head"><div><span className="cs-kicker">Score drivers</span><h3>Category health</h3></div></div><div className="cs-category-stack">{categories.map(([category, score]) => <div className="cs-category-row" key={category}><div><span>{category}</span><strong>{score}</strong></div><div className="cs-category-bar"><span style={{ width: `${Math.max(0, Math.min(100, ((score - 300) / 550) * 100))}%` }} /></div><small>{result.findings_by_category[category as keyof typeof result.findings_by_category]} findings</small></div>)}</div></section></div>
  </div>;
}

function PriorityList({ findings, select, openSonar }: { findings: Finding[]; select: (finding: Finding) => void; openSonar: () => void }) {
  if (findings.length === 0) return <div className="cs-empty-panel">No priority findings in the current baseline.</div>;
  return <div className="cs-priority-list">{findings.map((finding, index) => <div className="cs-priority-item" key={finding.id}><div className="cs-priority-rank">{String(index + 1).padStart(2, "0")}</div><div className="cs-priority-main"><div className="cs-priority-title"><strong>{compactPath(finding.file_path)}</strong><span className={`cs-severity ${finding.severity}`}>{finding.severity}</span></div><p>{finding.message}</p><div className="cs-priority-meta"><span>{finding.analyzer}</span><span>{finding.debt_points} debt points</span><span>{finding.category}</span></div></div><div className="cs-priority-actions"><button onClick={() => select(finding)}>Investigate</button><button className="accent" onClick={() => { select(finding); openSonar(); }}>Fix with Sonar</button></div></div>)}</div>;
}

function Assistant({ open, status, result, question, answer, asking, error, setQuestion, ask, close }: { open: boolean; status: AskSonarStatus | null; result: ScanResponse | null; question: string; answer: GroundedAnswerResponse | null; asking: boolean; error: string | null; setQuestion: (value: string) => void; ask: () => void; close: () => void }) {
  return <aside className={`cs-assistant ${open ? "open" : ""}`}><div className="cs-assistant-head"><div className="cs-assistant-brand"><span className="cs-sonar-pulse" /><div><strong>Ask Sonar</strong><small>{status?.configured ? `${status.provider} · grounded` : "Deterministic guidance"}</small></div></div><button onClick={close}>×</button></div><div className="cs-assistant-context"><span>Context</span><strong>{result ? `${repoName(result.repository)} · ${result.score} ${result.grade}` : "No active baseline"}</strong><small>{result?.scan_id ? `Scan ${result.scan_id.slice(0, 8)}` : "Run a scan to ground answers in repository evidence."}</small></div><div className="cs-assistant-body"><div className="cs-assistant-welcome"><span className="cs-kicker">Repository-aware copilot</span><h3>Ask about the score, risks, or next fix.</h3><p>Sonar can explain deterministic findings and prepare remediation plans. It cannot silently change the score.</p></div><div className="cs-quick-prompts">{["Why is my score this value?", "What should I fix first?", "Which file is the biggest risk?"].map((prompt) => <button key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>)}</div>{answer ? <div className="cs-answer"><span>SONAR</span><p>{answer.answer.answer}</p><small>{answer.answer.used_sources.length} grounded sources · score unchanged</small></div> : null}{error ? <Notice tone="warning" title="Ask Sonar unavailable">{error}</Notice> : null}</div><div className="cs-assistant-compose"><textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask Sonar about this repository…" /><div><small>{status?.configured ? "AI provider connected" : "Provider not configured"}</small><button className="cs-button primary" onClick={ask} disabled={!result?.scan_id || asking || !question.trim()}>{asking ? "Thinking…" : "Ask"}</button></div></div></aside>;
}

function Page({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) { return <div className="cs-page"><div className="cs-page-head"><span className="cs-kicker">Code Sonar</span><h1>{title}</h1><p>{subtitle}</p></div>{children}</div>; }
function Metric({ label, value, detail, tone = "normal" }: { label: string; value: string; detail: string; tone?: "normal" | "danger" }) { return <div className={`cs-metric ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>; }
function NoBaseline({ scan, scanning }: { scan: () => void; scanning: boolean }) { return <div className="cs-no-baseline"><div className="cs-logo large"><span /></div><h2>No baseline yet</h2><p>Run a deterministic scan to unlock this view.</p><button className="cs-button primary" onClick={scan} disabled={scanning}>{scanning ? "Scanning…" : "Run first scan"}</button></div>; }
function Notice({ tone, title, children }: { tone: "danger" | "warning"; title: string; children: ReactNode }) { return <div className={`cs-notice ${tone}`}><strong>{title}</strong><span>{children}</span></div>; }
function pageTitle(page: PageId): string { return ({ overview: "Code health overview", repositories: "Repositories", findings: "Findings", risk: "Risk map", history: "History", remediations: "Remediations", integrations: "Integrations", settings: "Engine & rules" })[page]; }
function compactPath(path: string): string { const parts = path.replace(/\\/g, "/").split("/"); return parts.length > 4 ? `…/${parts.slice(-4).join("/")}` : path.replace(/\\/g, "/"); }
function gradeLabel(grade: string): string { return ({ A: "Excellent", B: "Healthy", C: "Watch", D: "At risk", F: "High risk" } as Record<string, string>)[grade] ?? "Code health"; }
function scoreSummary(score: number, critical: number): string { if (critical > 0) return `${critical} critical finding${critical === 1 ? "" : "s"} require attention. Focus on concentrated production risk before broad cleanup.`; if (score >= 760) return "The repository is in strong shape. Protect the baseline and address emerging debt before it compounds."; if (score >= 650) return "The codebase is generally healthy, with a few concentrated areas that should be addressed next."; if (score >= 550) return "Technical debt is materially affecting maintainability. Prioritize the highest-risk files first."; return "Debt is significantly affecting code health. Use the priority queue to attack the highest-impact production risks first."; }

export default App;
