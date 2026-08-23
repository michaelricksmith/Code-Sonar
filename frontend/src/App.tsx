import { useEffect, useMemo, useState } from "react";

import {
  fetchAnalyzers,
  fetchHealth,
  runScan,
} from "./api/analyzers";
import type {
  AnalyzerMetadata,
  Finding,
  FilterState,
  ScanResponse,
  SortState,
} from "./api/analyzers";

import { AnalyzerMetadataPanel } from "./components/AnalyzerMetadataPanel";
import { CategoryBreakdownChart } from "./components/CategoryBreakdownChart";
import { FindingDetailDrawer } from "./components/FindingDetailDrawer";
import { FilterChips } from "./components/FilterChips";
import { ScoreChangeCallout } from "./components/ScoreChangeCallout";
import { SortableFindingsTable } from "./components/SortableFindingsTable";

const DEFAULT_REPO =
  "C:\\Users\\bookm\\.openclaw\\workspace\\code-sonar";

const EMPTY_FILTER: FilterState = {
  severities: new Set(),
  categories: new Set(),
  analyzers: new Set(),
  search: "",
};

const DEFAULT_SORT: SortState = { key: "severity", direction: "desc" };

function matchesSearch(f: Finding, search: string): boolean {
  if (!search.trim()) return true;
  const needle = search.trim().toLowerCase();
  return (
    f.file_path.toLowerCase().includes(needle) ||
    (f.symbol ?? "").toLowerCase().includes(needle) ||
    f.evidence.toLowerCase().includes(needle) ||
    f.message.toLowerCase().includes(needle) ||
    f.rule_id.toLowerCase().includes(needle)
  );
}

function App() {
  const [repoPath, setRepoPath] = useState<string>(DEFAULT_REPO);
  const [health, setHealth] = useState<string>("checking…");
  const [scanning, setScanning] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [analyzers, setAnalyzers] = useState<AnalyzerMetadata[]>([]);

  useEffect(() => {
    fetchHealth()
      .then((d) => setHealth(d.status))
      .catch(() => setHealth("unreachable"));
  }, []);

  useEffect(() => {
    fetchAnalyzers()
      .then(setAnalyzers)
      .catch(() => setAnalyzers([]));
  }, [result]);

  async function onScan(): Promise<void> {
    setScanning(true);
    setError(null);
    setResult(null);
    try {
      const data = await runScan({ repo_path: repoPath });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScanning(false);
    }
  }

  const filtered = useMemo(() => {
    if (!result) return [] as Finding[];
    return result.findings.filter((f) => {
      if (filter.severities.size > 0 && !filter.severities.has(f.severity)) {
        return false;
      }
      if (filter.categories.size > 0 && !filter.categories.has(f.category)) {
        return false;
      }
      if (filter.analyzers.size > 0 && !filter.analyzers.has(f.analyzer)) {
        return false;
      }
      if (!matchesSearch(f, filter.search)) {
        return false;
      }
      return true;
    });
  }, [result, filter]);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Code Sonar</h1>
          <p className="text-sm text-slate-400">
            Credit report for your codebase
          </p>
        </div>
        <div className="text-xs text-slate-500">
          API: <span className="text-slate-300">{health}</span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8 space-y-8">
        <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-5">
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Repository path
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
              placeholder="C:\\path\\to\\repo"
              spellCheck={false}
            />
            <button
              onClick={onScan}
              disabled={scanning}
              className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
            >
              {scanning ? "Scanning…" : "Run scan"}
            </button>
          </div>
          {error && (
            <div className="mt-3 rounded-md border border-rose-700 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
              {error}
            </div>
          )}
        </section>

        {result && (
          <>
            <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <SummaryCard
                title="Score"
                big={`${result.score}`}
                sub={
                  <>
                    Grade{" "}
                    <span
                      className={`font-bold ${
                        result.grade === "A"
                          ? "text-emerald-400"
                          : result.grade === "B"
                            ? "text-lime-400"
                              : result.grade === "C"
                                ? "text-yellow-400"
                                : result.grade === "D"
                                  ? "text-orange-400"
                                  : "text-rose-500"
                      }`}
                    >
                      {result.grade}
                    </span>
                  </>
                }
              />
              <SummaryCard
                title="Findings"
                big={`${result.finding_count}`}
                sub={`${result.total_debt_points} debt points`}
              />
              <SummaryCard
                title="Source breakdown"
                big={`${
                  (result.findings_source_breakdown?.source ?? 0) +
                  (result.findings_source_breakdown?.test ?? 0) +
                  (result.findings_source_breakdown?.fixture ?? 0)
                }`}
                sub={
                  <span className="text-xs text-slate-400">
                    source {result.findings_source_breakdown?.source ?? 0} ·
                    test {result.findings_source_breakdown?.test ?? 0} ·
                    fixture {result.findings_source_breakdown?.fixture ?? 0}
                  </span>
                }
              />
            </section>

            <ScoreChangeCallout
              result={result}
              analyzerCount={analyzers.length}
            />

            <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
              <h2 className="text-lg font-semibold mb-4">Category scores</h2>
              <div className="space-y-3">
                {(
                  Object.keys(result.category_scores) as Array<
                    keyof typeof result.category_scores
                  >
                ).map((c) => {
                  const catScore = result.category_scores[c];
                  const catFindings = result.findings_by_category[c];
                  return (
                    <div key={c}>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-300">{c}</span>
                        <span className="text-slate-400">
                          {catScore} · {catFindings} findings
                        </span>
                      </div>
                      <div className="mt-1 h-2 rounded-full bg-slate-700">
                        <div
                          className="h-2 rounded-full bg-sky-500"
                          style={{
                            width: `${Math.max(
                              0,
                              Math.min(
                                100,
                                ((catScore - 300) / 550) * 100,
                              ),
                            )}%`,
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <CategoryBreakdownChart
              findingsByCategory={result.findings_by_category}
            />

            <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold">
                  Findings ({filtered.length} / {result.findings.length})
                </h2>
              </div>
              <FilterChips
                findings={result.findings}
                analyzers={analyzers}
                filter={filter}
                onChange={setFilter}
              />
              <div className="mt-4">
                <SortableFindingsTable
                  findings={filtered}
                  onSelect={setSelected}
                  sort={sort}
                  onSortChange={setSort}
                />
              </div>
            </section>

            <AnalyzerMetadataPanel
              refreshKey={result ? Date.now() : undefined}
            />

            <footer className="text-xs text-slate-500">
              Scanned at {result.scanned_at}
            </footer>
          </>
        )}
      </main>

      <FindingDetailDrawer finding={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function SummaryCard({
  title,
  big,
  sub,
}: {
  title: string;
  big: string;
  sub: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
      <div className="text-xs uppercase tracking-wide text-slate-400">
        {title}
      </div>
      <div className="mt-2 text-6xl font-bold text-slate-100">{big}</div>
      <div className="mt-1 text-sm text-slate-400">{sub}</div>
    </div>
  );
}

export default App;
