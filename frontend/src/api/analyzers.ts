// Code Sonar — analyzer registry / API client + drift API client.
//
// Provides a typed surface over the backend's analyzer registry
// (`GET /api/analyzers`), scan endpoint (`POST /api/scan`),
// history endpoints (`GET /api/history/list`, `GET /api/history/latest`,
// `GET /api/history/{scan_id}`), and drift endpoint (`GET /api/drift`).

export type Severity = "info" | "warning" | "error" | "critical";

export type Category =
  | "complexity"
  | "staleness"
  | "security"
  | "duplication"
  | "testing"
  | "maintainability";

export type DriftClassification =
  | "new"
  | "resolved"
  | "persistent"
  | "worsened"
  | "improved";

export interface AnalyzerMetadata {
  name: string;
  analyzer_id: string;
  category: string;
  threshold: number | null;
}

export interface Finding {
  id: string;
  rule_id: string;
  category: Category;
  severity: Severity;
  confidence: number;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  symbol: string | null;
  evidence: string;
  message: string;
  suggestion: string | null;
  debt_points: number;
  remediation_effort: string | null;
  analyzer: string;
  metadata: Record<string, unknown>;
}

export interface ScanSummary {
  total_findings: number;
  total_debt_points: number;
  score: number;
  grade: string;
  by_severity: Record<Severity, number>;
  by_category: Record<Category, number>;
}

export interface ScanResponse {
  repository: string;
  scanned_at: string;
  score: number;
  grade: string;
  total_debt_points: number;
  finding_count: number;
  category_scores: Record<Category, number>;
  severity_distribution: Record<Severity, number>;
  findings_by_category: Record<Category, number>;
  findings_source_breakdown?: {
    source: number;
    test: number;
    fixture: number;
  };
  findings: Finding[];
  summary: ScanSummary;
}

export interface ScanRequest {
  repo_path: string;
}

export interface FilterState {
  severities: Set<Severity>;
  categories: Set<Category>;
  analyzers: Set<string>;
  search: string;
}

export type SortKey =
  | "severity"
  | "file_path"
  | "debt_points"
  | "line_start"
  | "analyzer";

export interface SortState {
  key: SortKey;
  direction: "asc" | "desc";
}

// --- Drift types (Checkpoint 6, Lane 3) -------------------------------------

export interface DriftScanRef {
  scan_id: string;
  scanned_at: string;
  score: number;
  grade: string;
  total_debt_points: number;
  finding_count: number;
}

export interface DriftSummary {
  score_delta: number;
  debt_delta: number;
  finding_delta: number;
  new_count: number;
  resolved_count: number;
  persistent_count: number;
  worsened_count: number;
  improved_count: number;
  baseline: DriftScanRef;
  current: DriftScanRef;
}

export interface DriftFinding {
  finding_id: string;
  classification: DriftClassification;
  rule_id: string;
  category: Category;
  analyzer: string;
  severity: Severity;
  confidence: number;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  symbol: string | null;
  debt_points: number;
  baseline_severity: Severity | null;
  baseline_debt_points: number | null;
  baseline_risk: number | null;
  current_severity: Severity | null;
  current_debt_points: number | null;
  current_risk: number | null;
  message: string;
  suggestion: string | null;
  risk_delta: number;
}

export interface DriftBucketCounts {
  new: number;
  resolved: number;
  persistent: number;
  worsened: number;
  improved: number;
  score_delta: number;
  debt_delta: number;
}

export interface DriftResult {
  summary: DriftSummary;
  findings: DriftFinding[];
  by_category: Record<string, DriftBucketCounts>;
  by_analyzer: Record<string, DriftBucketCounts>;
  by_severity: Record<string, DriftBucketCounts>;
}

const API_BASE = "/api";

export async function fetchAnalyzers(): Promise<AnalyzerMetadata[]> {
  const res = await fetch(`${API_BASE}/analyzers`);
  if (!res.ok) {
    throw new Error(`Failed to fetch analyzers (HTTP ${res.status})`);
  }
  const data = await res.json();
  return (data.analyzers ?? []) as AnalyzerMetadata[];
}

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed (HTTP ${res.status})`);
  }
  return res.json();
}

export async function runScan(req: ScanRequest): Promise<ScanResponse> {
  const res = await fetch(`${API_BASE}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail ?? `Scan failed (HTTP ${res.status})`);
  }
  return data as ScanResponse;
}

export async function fetchDrift(
  repoPath: string,
  opts: { from_scan_id?: string; to_scan_id?: string } = {},
): Promise<DriftResult> {
  const params = new URLSearchParams({ repo_path: repoPath });
  if (opts.from_scan_id) params.set("from_scan_id", opts.from_scan_id);
  if (opts.to_scan_id) params.set("to_scan_id", opts.to_scan_id);
  const res = await fetch(`${API_BASE}/drift?${params.toString()}`);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail ?? `Drift fetch failed (HTTP ${res.status})`);
  }
  return data as DriftResult;
}

export function severityRank(severity: Severity): number {
  switch (severity) {
    case "critical":
      return 4;
    case "error":
      return 3;
    case "warning":
      return 2;
    case "info":
    default:
      return 1;
  }
}

export function gradeColor(grade: string): string {
  switch (grade) {
    case "A":
      return "text-emerald-400";
    case "B":
      return "text-lime-400";
    case "C":
      return "text-yellow-400";
    case "D":
      return "text-orange-400";
    case "F":
    default:
      return "text-rose-500";
  }
}

export const SEVERITY_COLOR: Record<Severity, string> = {
  info: "bg-sky-500/20 text-sky-300 ring-sky-500/40",
  warning: "bg-amber-500/20 text-amber-300 ring-amber-500/40",
  error: "bg-rose-500/20 text-rose-300 ring-rose-500/40",
  critical: "bg-fuchsia-600/30 text-fuchsia-200 ring-fuchsia-500/60",
};

export const SEVERITIES: Severity[] = ["info", "warning", "error", "critical"];
export const CATEGORIES: Category[] = [
  "complexity",
  "staleness",
  "security",
  "duplication",
  "testing",
  "maintainability",
];

export const DRIFT_CLASSIFICATIONS: DriftClassification[] = [
  "new",
  "resolved",
  "persistent",
  "worsened",
  "improved",
];
