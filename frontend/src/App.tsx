import { useEffect, useState } from 'react'

type Severity = 'info' | 'warning' | 'error' | 'critical'
type Category =
  | 'complexity'
  | 'staleness'
  | 'security'
  | 'duplication'
  | 'testing'
  | 'maintainability'

interface Finding {
  id: string
  rule_id: string
  category: Category
  severity: Severity
  confidence: number
  file_path: string
  line_start: number | null
  line_end: number | null
  symbol: string | null
  evidence: string
  message: string
  suggestion: string | null
  debt_points: number
  remediation_effort: string | null
  analyzer: string
  metadata: Record<string, unknown>
}

interface ScanSummary {
  total_findings: number
  total_debt_points: number
  score: number
  grade: string
  by_severity: Record<Severity, number>
  by_category: Record<Category, number>
}

interface ScanResponse {
  repository: string
  scanned_at: string
  score: number
  grade: string
  total_debt_points: number
  finding_count: number
  category_scores: Record<Category, number>
  severity_distribution: Record<Severity, number>
  findings_by_category: Record<Category, number>
  findings: Finding[]
  summary: ScanSummary
}

const SEVERITY_COLOR: Record<Severity, string> = {
  info: 'bg-sky-500/20 text-sky-300 ring-sky-500/40',
  warning: 'bg-amber-500/20 text-amber-300 ring-amber-500/40',
  error: 'bg-rose-500/20 text-rose-300 ring-rose-500/40',
  critical: 'bg-fuchsia-600/30 text-fuchsia-200 ring-fuchsia-500/60',
}

const GRADE_COLOR: Record<string, string> = {
  A: 'text-emerald-400',
  B: 'text-lime-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  F: 'text-rose-500',
}

function gradeColor(grade: string): string {
  return GRADE_COLOR[grade] ?? 'text-slate-300'
}

function App() {
  const defaultRepo = 'C:\\Users\\bookm\\.openclaw\\workspace\\code-sonar'
  const [repoPath, setRepoPath] = useState<string>(defaultRepo)
  const [health, setHealth] = useState<string>('checking…')
  const [scanning, setScanning] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ScanResponse | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setHealth(d.status ?? 'unknown'))
      .catch(() => setHealth('unreachable'))
  }, [])

  async function runScan(): Promise<void> {
    setScanning(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: repoPath }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail ?? `HTTP ${res.status}`)
        return
      }
      setResult(data as ScanResponse)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Code Sonar</h1>
          <p className="text-sm text-slate-400">Credit report for your codebase</p>
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
              onClick={runScan}
              disabled={scanning}
              className="rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700"
            >
              {scanning ? 'Scanning…' : 'Run scan'}
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
              <div className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
                <div className="text-xs uppercase tracking-wide text-slate-400">
                  Score
                </div>
                <div
                  className={`mt-2 text-6xl font-bold ${gradeColor(result.grade)}`}
                >
                  {result.score}
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  Grade{' '}
                  <span className={`font-bold ${gradeColor(result.grade)}`}>
                    {result.grade}
                  </span>
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
                <div className="text-xs uppercase tracking-wide text-slate-400">
                  Findings
                </div>
                <div className="mt-2 text-6xl font-bold text-slate-100">
                  {result.finding_count}
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  {result.total_debt_points} debt points
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
                <div className="text-xs uppercase tracking-wide text-slate-400">
                  Severity mix
                </div>
                <div className="mt-3 space-y-1 text-sm">
                  {(Object.keys(result.severity_distribution) as Severity[]).map(
                    (s) => (
                      <div key={s} className="flex items-center justify-between">
                        <span
                          className={`inline-flex rounded px-2 py-0.5 text-xs ring-1 ${SEVERITY_COLOR[s]}`}
                        >
                          {s}
                        </span>
                        <span className="text-slate-200">
                          {result.severity_distribution[s]}
                        </span>
                      </div>
                    ),
                  )}
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
              <h2 className="text-lg font-semibold mb-4">Category scores</h2>
              <div className="space-y-3">
                {(Object.keys(result.category_scores) as Category[]).map((c) => {
                  const catScore = result.category_scores[c]
                  const catFindings = result.findings_by_category[c]
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
                            width: `${Math.max(0, Math.min(100, ((catScore - 300) / 550) * 100))}%`,
                          }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
              <h2 className="text-lg font-semibold mb-4">
                Findings ({result.findings.length})
              </h2>
              {result.findings.length === 0 ? (
                <p className="text-sm text-slate-400">
                  No findings — clean scan.
                </p>
              ) : (
                <ul className="divide-y divide-slate-800">
                  {result.findings.map((f) => (
                    <li key={f.id} className="py-3">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span
                              className={`inline-flex rounded px-2 py-0.5 text-xs ring-1 ${SEVERITY_COLOR[f.severity]}`}
                            >
                              {f.severity}
                            </span>
                            <code className="text-xs text-slate-400">
                              {f.rule_id}
                            </code>
                          </div>
                          <div className="mt-1 font-mono text-xs text-slate-300">
                            {f.file_path}
                            {f.line_start != null && `:${f.line_start}`}
                          </div>
                          <p className="mt-1 text-sm text-slate-200">
                            {f.message}
                          </p>
                          {f.suggestion && (
                            <p className="mt-1 text-xs text-slate-400">
                              Fix: {f.suggestion}
                            </p>
                          )}
                        </div>
                        <div className="shrink-0 text-right text-xs text-slate-400">
                          <div>+{f.debt_points} pts</div>
                          {f.remediation_effort && (
                            <div className="mt-0.5">{f.remediation_effort}</div>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <footer className="text-xs text-slate-500">
              Scanned at {result.scanned_at}
            </footer>
          </>
        )}
      </main>
    </div>
  )
}

export default App