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
import {
  askSonar,
  fetchAskSonarStatus,
} from "./api/askSonar";
import type {
  AskSonarStatus,
  GroundedAnswerResponse,
} from "./api/askSonar";

import { AnalyzerMetadataPanel } from "./components/AnalyzerMetadataPanel";
import { CategoryBreakdownChart } from "./components/CategoryBreakdownChart";
import { DriftView } from "./components/DriftView";
import { FindingDetailDrawer } from "./components/FindingDetailDrawer";
import { FilterChips } from "./components/FilterChips";
import { FirstScanGuide } from "./components/FirstScanGuide";
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
  | "projects"
  | "findings"
  | "hotspots"
  | "history"
  | "ask-sonar"
  | "settings";

const NAV_ITEMS: Array<{ page: NavPage; label: string; short: string }> = [
  { page: "overview", label: "Command Overview", short: "OV" },
  { page: "projects", label: "Repositories", short: "GH" },
  { page: "findings", label: "Findings", short: "FX" },
  { page: "hotspots", label: "Risk Hotspots", short: "RH" },
  { page: "history", label: "History & Drift", short: "HD" },
  { page: "ask-sonar", label: "Ask Sonar", short: "AI" },
  { page: "settings", label: "Engine & Rules", short: "ER" },
];

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
  const [askStatus, setAskStatus] = useState<AskSonarStatus | null>(null);
  const [question, setQuestion] = useState("Why is my score this value, and what should I fix first?");
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

  const criticalCount = result?.severity_distribution.critical ?? 0;
  const hotspotCount = result?.top_hotspots?.length ?? 0;

  async function onScan(): Promise<void> {
    setScanning(true);
    setError(null);
    setSelected(null);
    setDrift(null);
    setDriftError(null);
    setAnswer(null);
    try {
      const data = await runScan({ repo_path: repoPath });
      setResult(data);
      setActivePage("overview");
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
      if (message.includes("HTTP 400") || message.includes("HTTP 404")) {
        setDrift(null);
        setDriftError("Run at least two scans of this repository to compute drift.");
      } else {
        setDriftError(message);
      }
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

  return (
    <div className="sonar-app-shell">
      <aside className="sonar-sidebar">
        <div>
          <div className="sonar-brand">
            <div className="sonar-mark"><span /></div>
            <div>
              <div className="sonar-brand-title">CODE SONAR</div>
              <div className="sonar-brand-subtitle">Technical Debt Intelligence</div>
            </div>
          </div>

          <div className="sonar-nav-label">Risk intelligence</div>
          <nav className="sonar-nav">
            {NAV_ITEMS.map((item) => {
              let badge: string | number | null = null;
              if (item.page === "findings" && result) badge = result.finding_count;
              if (item.page === "hotspots" && hotspotCount > 0) badge = hotspotCount;
              if (item.page === "ask-sonar") badge = "AI";
              return (
                <button
                  key={item.page}
                  type="button"
                  onClick={() => setActivePage(item.page)}
                  className={`sonar-nav-item ${activePage === item.page ? "active" : ""}`}
                >
                  <span className="sonar-nav-icon">{item.short}</span>
                  <span className="sonar-nav-text">{item.label}</span>
                  {badge !== null && <span className="sonar-nav-badge">{badge}</span>}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="sonar-side-status">
          <div className="sonar-status-row">
            <span>API</span>
            <span className={health === "ok" ? "status-good" : "status-warn"}>{health}</span>
          </div>
          <div className="sonar-status-row">
            <span>Deterministic engine</span>
            <span className="status-good">authoritative</span>
          </div>
          <div className="sonar-side-meta">
            {analyzers.length || 0} analyzers · score range 300–850
          </div>
        </div>
      </aside>

      <div className="sonar-main-shell">
        <div className="sonar-telemetry-bar">
          <span><i className="telemetry-dot" /> ENGINE ONLINE</span>
          <span>API {health}</span>
          <span>{result ? `SCAN ${result.scan_id?.slice(0, 8) ?? "LOCAL"}` : "NO ACTIVE BASELINE"}</span>
          <span>{askStatus?.configured ? `ASK SONAR · ${askStatus.provider}` : "ASK SONAR · deterministic only"}</span>
        </div>

        <header className="sonar-header">
          <div className="sonar-repo-control">
            <div className="sonar-eyebrow">Repository target</div>
            <input
              value={repoPath}
              onChange={(event) => setRepoPath(event.target.value)}
              className="sonar-repo-input"
              spellCheck={false}
            />
          </div>
          <div className="sonar-header-actions">
            {criticalCount > 0 && <span className="sonar-critical-pill">{criticalCount} critical</span>}
            <button type="button" className="sonar-secondary-button" onClick={() => setActivePage("ask-sonar")}>Ask Sonar</button>
            <button type="button" className="sonar-primary-button" onClick={onScan} disabled={scanning || !repoPath.trim()}>
              {scanning ? "Scanning…" : result ? "Scan again" : "Attach & scan"}
            </button>
          </div>
        </header>

        <main className="sonar-content">
          {error && <Notice tone="danger" title="Repository scan failed">{error}</Notice>}

          {activePage === "overview" && (
            <OverviewPage
              result={result}
              scanning={scanning}
              onScan={onScan}
              onNavigate={setActivePage}
              onSelectFinding={setSelected}
            />
          )}

          {activePage === "projects" && (
            <PageFrame title="Repositories" subtitle="Connect GitHub, manage monitored projects, and trigger deterministic scans.">
              <ProjectDashboardPanel />
            </PageFrame>
          )}

          {activePage === "findings" && (
            <PageFrame title="Findings" subtitle="Filter, inspect, and prioritize the evidence behind the deterministic score.">
              {!result ? (
                <EmptyState onScan={onScan} scanning={scanning} />
              ) : (
                <div className="sonar-panel">
                  <div className="sonar-panel-heading">
                    <div>
                      <div className="sonar-panel-title">Finding inventory</div>
                      <div className="sonar-panel-subtitle">{filtered.length} of {result.findings.length} findings shown</div>
                    </div>
                    {fileFilter && (
                      <button type="button" className="sonar-text-button" onClick={() => setFileFilter(null)}>Clear file filter</button>
                    )}
                  </div>
                  <FilterChips findings={result.findings} analyzers={analyzers} filter={filter} onChange={setFilter} />
                  <div className="mt-4">
                    <SortableFindingsTable findings={filtered} onSelect={setSelected} sort={sort} onSortChange={setSort} />
                  </div>
                </div>
              )}
            </PageFrame>
          )}

          {activePage === "hotspots" && (
            <PageFrame title="Risk Hotspots" subtitle="Files where multiple analyzers agree risk is concentrated.">
              {result?.top_hotspots?.length ? (
                <RiskHotspots
                  hotspots={result.top_hotspots}
                  hotspotSummary={{
                    total_files: result.top_hotspots.length,
                    files_with_findings: new Set(result.findings.map((finding) => finding.file_path)).size,
                    total_findings: result.finding_count,
                    total_debt: result.total_debt_points,
                  }}
                  findings={result.findings}
                  onFilterByFile={(path) => {
                    setFileFilter(path);
                    setActivePage("findings");
                  }}
                  activeFileFilter={fileFilter}
                />
              ) : <EmptyState onScan={onScan} scanning={scanning} />}
            </PageFrame>
          )}

          {activePage === "history" && (
            <PageFrame title="History & Drift" subtitle="Compare the current baseline with the previous scan without changing score authority.">
              <div className="sonar-panel">
                <div className="sonar-panel-heading">
                  <div>
                    <div className="sonar-panel-title">Drift comparison</div>
                    <div className="sonar-panel-subtitle">New, resolved, persistent, worsened, and improved findings.</div>
                  </div>
                  <button type="button" className="sonar-primary-button" onClick={onShowDrift} disabled={!result || driftLoading}>
                    {driftLoading ? "Comparing…" : "Compare previous scan"}
                  </button>
                </div>
                {driftError && <Notice tone="warning" title="Drift unavailable">{driftError}</Notice>}
                {drift ? <DriftView drift={drift} /> : <div className="sonar-empty-inline">Run a comparison to visualize repository drift.</div>}
              </div>
            </PageFrame>
          )}

          {activePage === "ask-sonar" && (
            <PageFrame title="Ask Sonar" subtitle="Grounded explanations and remediation guidance. Deterministic scoring remains authoritative.">
              <div className="sonar-ai-grid">
                <section className="sonar-panel sonar-ai-core">
                  <div className="sonar-ai-orb"><span>SONAR</span></div>
                  <div className="sonar-ai-status">
                    <div className="sonar-eyebrow">Intelligence status</div>
                    <div className="sonar-panel-title">{askStatus?.configured ? "Conversational provider ready" : "Deterministic guidance ready"}</div>
                    <p>{askStatus?.configured ? `${askStatus.provider} · ${askStatus.model}` : "Configure an approved provider to enable generated conversational explanations."}</p>
                  </div>
                </section>

                <section className="sonar-panel sonar-chat-panel">
                  <label className="sonar-field-label" htmlFor="ask-sonar-question">Question about this scan</label>
                  <textarea
                    id="ask-sonar-question"
                    className="sonar-question-input"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    rows={4}
                    placeholder="Why did testing debt lower my score?"
                  />
                  <div className="sonar-chat-actions">
                    <span className="sonar-panel-subtitle">{result?.scan_id ? `Grounded to scan ${result.scan_id.slice(0, 8)}` : "Run a scan first"}</span>
                    <button type="button" className="sonar-primary-button" onClick={onAskSonar} disabled={!result?.scan_id || !askStatus?.configured || asking || !question.trim()}>
                      {asking ? "Analyzing…" : "Ask Sonar"}
                    </button>
                  </div>
                  {askError && <Notice tone="danger" title="Ask Sonar could not answer">{askError}</Notice>}
                  {answer && (
                    <div className="sonar-answer">
                      <div className="sonar-eyebrow">Grounded answer</div>
                      <p>{answer.answer.answer}</p>
                      <div className="sonar-answer-meta">Score remains {answer.deterministic_score} ({answer.deterministic_grade}) · {answer.answer.used_sources.length} cited sources</div>
                    </div>
                  )}
                </section>
              </div>

              {result && <FirstScanGuide result={result} onSelectFinding={setSelected} />}
            </PageFrame>
          )}

          {activePage === "settings" && (
            <PageFrame title="Engine & Rules" subtitle="Inspect analyzer thresholds and runtime state. Score configuration is intentionally not editable here.">
              <div className="sonar-settings-grid">
                <MetricCard label="API" value={health} meta="runtime health" />
                <MetricCard label="Analyzers" value={String(analyzers.length)} meta="deterministic rules" />
                <MetricCard label="Authority" value="Code Sonar" meta="ML remains advisory" />
              </div>
              <AnalyzerMetadataPanel refreshKey={result ? result.scanned_at : undefined} />
            </PageFrame>
          )}
        </main>
      </div>

      <FindingDetailDrawer
        finding={selected}
        scanId={result?.scan_id ?? null}
        currentScore={result?.score ?? null}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}

function OverviewPage({
  result,
  scanning,
  onScan,
  onNavigate,
  onSelectFinding,
}: {
  result: ScanResponse | null;
  scanning: boolean;
  onScan: () => void;
  onNavigate: (page: NavPage) => void;
  onSelectFinding: (finding: Finding) => void;
}) {
  if (!result) {
    return (
      <div className="sonar-start-state">
        <div className="sonar-eyebrow">Start with a baseline</div>
        <h1>Credit report for your codebase.</h1>
        <p>Attach a repository to generate deterministic findings, debt points, hotspots, and a score you can track over time.</p>
        <button type="button" className="sonar-primary-button sonar-large-button" onClick={onScan} disabled={scanning}>{scanning ? "Scanning…" : "Run baseline scan"}</button>
      </div>
    );
  }

  const sourceBreakdown = result.findings_source_breakdown ?? { source: 0, test: 0, fixture: 0 };
  return (
    <div className="sonar-page-stack">
      <div className="sonar-page-heading">
        <div>
          <div className="sonar-eyebrow">Current baseline</div>
          <h1>Command Overview</h1>
          <p>Deterministic technical-debt intelligence for the active repository.</p>
        </div>
        <div className="sonar-baseline-id">SCAN {result.scan_id?.slice(0, 12) ?? "LOCAL"}</div>
      </div>

      <section className="sonar-score-grid">
        <div className="sonar-score-card sonar-score-primary">
          <div className="sonar-score-ring">
            <div><strong>{result.score}</strong><span>/850</span></div>
          </div>
          <div>
            <div className="sonar-eyebrow">Code health score</div>
            <div className={`sonar-grade grade-${result.grade.toLowerCase()}`}>{result.grade}</div>
            <div className="sonar-panel-subtitle">Deterministic · reproducible · source-aware</div>
          </div>
        </div>
        <MetricCard label="Findings" value={String(result.finding_count)} meta={`${result.total_debt_points} raw debt points`} />
        <MetricCard label="Production" value={String(sourceBreakdown.source)} meta={`${sourceBreakdown.test} test · ${sourceBreakdown.fixture} fixture`} />
        <MetricCard label="Critical" value={String(result.severity_distribution.critical)} meta={`${result.severity_distribution.error} errors`} danger={result.severity_distribution.critical > 0} />
      </section>

      <FirstScanGuide result={result} onSelectFinding={onSelectFinding} />

      <div className="sonar-overview-grid">
        <section className="sonar-panel">
          <div className="sonar-panel-heading">
            <div>
              <div className="sonar-panel-title">Category health</div>
              <div className="sonar-panel-subtitle">Scores show where debt is concentrated.</div>
            </div>
          </div>
          <div className="sonar-category-list">
            {Object.entries(result.category_scores).map(([category, score]) => (
              <div className="sonar-category-row" key={category}>
                <div className="sonar-category-head"><span>{category}</span><span>{score} · {result.findings_by_category[category as keyof typeof result.findings_by_category]} findings</span></div>
                <div className="sonar-category-track"><span style={{ width: `${Math.max(0, Math.min(100, ((score - 300) / 550) * 100))}%` }} /></div>
              </div>
            ))}
          </div>
        </section>
        <section className="sonar-panel">
          <div className="sonar-panel-heading">
            <div>
              <div className="sonar-panel-title">Finding distribution</div>
              <div className="sonar-panel-subtitle">Debt concentration by category.</div>
            </div>
          </div>
          <CategoryBreakdownChart findingsByCategory={result.findings_by_category} />
        </section>
      </div>

      {result.top_hotspots?.length ? (
        <section className="sonar-panel">
          <div className="sonar-panel-heading">
            <div>
              <div className="sonar-panel-title">Top risk vectors</div>
              <div className="sonar-panel-subtitle">Highest-value files to investigate next.</div>
            </div>
            <button type="button" className="sonar-text-button" onClick={() => onNavigate("hotspots")}>View all hotspots</button>
          </div>
          <div className="sonar-hotspot-preview">
            {result.top_hotspots.slice(0, 5).map((hotspot, index) => (
              <button type="button" key={hotspot.file_path} className="sonar-hotspot-row" onClick={() => onNavigate("hotspots")}>
                <span className="sonar-hotspot-rank">#{index + 1}</span>
                <span className="sonar-hotspot-file">{hotspot.file_path}</span>
                <span>{hotspot.finding_count} findings</span>
                <span>{hotspot.debt_total} debt</span>
                <strong>{hotspot.score}</strong>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function PageFrame({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="sonar-page-stack">
      <div className="sonar-page-heading">
        <div>
          <div className="sonar-eyebrow">Code Sonar</div>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
      </div>
      {children}
    </div>
  );
}

function MetricCard({ label, value, meta, danger = false }: { label: string; value: string; meta: string; danger?: boolean }) {
  return (
    <div className={`sonar-metric-card ${danger ? "danger" : ""}`}>
      <div className="sonar-eyebrow">{label}</div>
      <div className="sonar-metric-value">{value}</div>
      <div className="sonar-panel-subtitle">{meta}</div>
    </div>
  );
}

function Notice({ tone, title, children }: { tone: "danger" | "warning"; title: string; children: ReactNode }) {
  return (
    <div className={`sonar-notice ${tone}`}>
      <strong>{title}</strong>
      <span>{children}</span>
    </div>
  );
}

function EmptyState({ onScan, scanning }: { onScan: () => void; scanning: boolean }) {
  return (
    <div className="sonar-empty-state">
      <div className="sonar-eyebrow">No active scan</div>
      <h2>Establish a baseline first.</h2>
      <p>Run a deterministic scan, then return here to inspect this view.</p>
      <button type="button" className="sonar-primary-button" onClick={onScan} disabled={scanning}>{scanning ? "Scanning…" : "Run scan"}</button>
    </div>
  );
}

export default App;
