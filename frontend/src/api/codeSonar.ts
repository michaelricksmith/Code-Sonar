/// <reference types="vite/client" />

/**
 * Code Sonar backend API client.
 *
 * All endpoints consumed here are real backend endpoints. There is no
 * mock data, no fake fallback, no fabricated analytics. If a request
 * fails, the typed Error propagates and the UI must render an error
 * state (the calling component is responsible for catching/handling).
 *
 * Backend base URL is configurable via the Vite env var
 * `VITE_API_BASE`. Default: http://127.0.0.1:8000.
 *
 * Backend endpoint contract (see backend/app/main.py):
 *   GET  /health
 *   GET  /api/analyzers
 *   POST /api/scan                        body: { repo_path: string }
 *   GET  /api/hotspots?repo_path=...&limit=50
 *   GET  /api/history/list?repository_id=...&limit=50
 *   GET  /api/history/latest?repo_path=...
 *   GET  /api/history/{scan_id}
 *   GET  /api/drift?repo_path=...&from_scan_id=...&to_scan_id=...
 *   GET  /api/telemetry/latest?repo_path=...
 *   GET  /api/telemetry/history?repo_path=...&limit=50
 *   GET  /api/telemetry/scan/{scan_id}
 *   GET  /api/projection?repo_path=...&horizon=next_scan|7d|30d
 *   GET  /api/scan/stages/{scan_id}
 */

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const RAW_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ||
  'http://127.0.0.1:8000';

export const API_BASE_URL: string = RAW_BASE.replace(/\/+$/, '');

// ---------------------------------------------------------------------------
// Domain types — mirror backend Pydantic models verbatim.
// ---------------------------------------------------------------------------

/** Score is an integer in [300, 850] (credit-report style). */
export type ScoreRange = number;

export type Grade =
  | 'A+'
  | 'A'
  | 'A-'
  | 'B+'
  | 'B'
  | 'B-'
  | 'C+'
  | 'C'
  | 'C-'
  | 'D'
  | 'F';

export type Severity = 'info' | 'warning' | 'error' | 'critical';

export type Category =
  | 'complexity'
  | 'staleness'
  | 'security'
  | 'duplication'
  | 'testing'
  | 'maintainability';

export type FindingStatus = 'open' | 'in_triage' | 'suppressed' | 'resolved';

/**
 * A normalized finding from the backend. Field names use snake_case to
 * match the JSON contract from /api/scan and /api/history/{scan_id}.
 * The frontend UI types (in src/types.ts) use camelCase; use
 * `toFrontendFinding` to map between them.
 */
export interface ApiFinding {
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
  detected_at: string;
}

export interface ApiSummary {
  total_findings: number;
  total_debt_points: number;
  score: ScoreRange;
  grade: Grade;
  by_severity: Record<Severity, number>;
  by_category: Record<Category, number>;
}

export interface ApiScanResponse {
  repository: string;
  scanned_at: string;
  score: ScoreRange;
  grade: Grade;
  total_debt_points: number;
  finding_count: number;
  category_scores: Record<Category, ScoreRange>;
  severity_distribution: Record<Severity, number>;
  findings_by_category: Record<Category, number>;
  findings: ApiFinding[];
  summary: ApiSummary;
  top_hotspots: ApiHotspot[];
}

export interface ApiHotspot {
  file_path: string;
  score: number;
  debt_total: number;
  finding_count: number;
  severity_max: Severity;
  severity_max_weight: number;
  analyzer_diversity: number;
  analyzer_breakdown: Record<string, number>;
  severity_breakdown: Record<string, number>;
  category_breakdown: Record<string, number>;
  complexity_max: number;
  size_max: number;
  nesting_max: number;
  contributing_finding_ids: string[];
}

export interface ApiHotspotResult {
  hotspots: ApiHotspot[];
  total_files: number;
  files_with_findings: number;
  total_findings: number;
  total_debt: number;
}

export interface ApiScanSummary {
  scan_id: string;
  repository_id: string;
  repository_path: string;
  scanned_at: string;
  schema_version: string;
  score: ScoreRange;
  grade: Grade;
  total_debt_points: number;
  finding_count: number;
  category_scores: Record<Category, ScoreRange>;
  severity_distribution: Record<Severity, number>;
  findings_by_category: Record<Category, number>;
  findings_source_breakdown: Record<string, number>;
}

export interface ApiScanRecord extends ApiScanSummary {
  findings: ApiFinding[];
}

export interface ApiHistoryListResponse {
  count: number;
  scans: ApiScanSummary[];
}

export interface ApiDriftSummary {
  score_delta: number;
  debt_delta: number;
  finding_delta: number;
  new_count: number;
  resolved_count: number;
  persistent_count: number;
  worsened_count: number;
  improved_count: number;
  baseline: {
    scan_id: string;
    scanned_at: string;
    score: ScoreRange;
    grade: Grade;
    total_debt_points: number;
    finding_count: number;
  };
  current: {
    scan_id: string;
    scanned_at: string;
    score: ScoreRange;
    grade: Grade;
    total_debt_points: number;
    finding_count: number;
  };
}

export interface ApiDriftFinding {
  finding_id: string;
  classification: 'new' | 'resolved' | 'persistent' | 'worsened' | 'improved';
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
  baseline_severity: string | null;
  baseline_debt_points: number | null;
  baseline_risk: number | null;
  current_severity: string | null;
  current_debt_points: number | null;
  current_risk: number | null;
  message: string;
  suggestion: string | null;
  risk_delta: number;
}

export interface ApiDriftResult {
  summary: ApiDriftSummary;
  findings: ApiDriftFinding[];
  // Bucket drill-downs (best-effort shape).
  by_category?: Record<string, unknown>;
  by_analyzer?: Record<string, unknown>;
  by_severity?: Record<string, unknown>;
}

export interface ApiAnalyzerTelemetry {
  analyzer_id: string;
  findings_count: number;
  duration_ms: number;
  status: 'success' | 'warning' | 'error' | 'skipped';
  detail?: string | null;
}

export interface ApiTelemetrySnapshot {
  repository_id: string;
  scan_id: string;
  scanned_at: string;
  scan_duration_ms: number;
  files_discovered: number;
  files_analyzed: number;
  files_skipped: number;
  analyzers_total: number;
  analyzers_successful: number;
  analyzers_warning: number;
  analyzers_failed: number;
  analyzer_telemetry: ApiAnalyzerTelemetry[];
  score: ScoreRange;
  grade: Grade;
  total_debt_points: number;
  finding_count: number;
  severity_distribution: Record<Severity, number>;
  category_distribution: Record<Category, number>;
  hotspot_count: number;
  highest_risk_files: string[];
  has_prior: boolean;
  score_delta: number;
  debt_delta: number;
  finding_delta: number;
  new_count: number;
  resolved_count: number;
  worsened_count: number;
  improved_count: number;
  persistent_count: number;
  prior_scan_count: number;
  scan_frequency_per_day: number | null;
  trend_direction_score: string;
  risk_velocity_score: number | null;
  risk_velocity_debt: number | null;
  radar_axes: Record<string, number>;
}

export interface ApiTelemetryHistoryResponse {
  count: number;
  telemetry: ApiTelemetrySnapshot[];
}

export type ProjectionHorizon = 'next_scan' | '7d' | '30d';

export type ProjectionDirection =
  | 'insufficient_history'
  | 'improving'
  | 'degrading'
  | 'flat';

export type ProjectionConfidence =
  | 'insufficient_history'
  | 'early_trend'
  | 'moderate'
  | 'stronger';

export interface ApiProjectionSignal {
  name: string;
  value: string;
  numeric: number | null;
}

export interface ApiRiskProjection {
  repository_id: string;
  horizon: ProjectionHorizon;
  current_score: ScoreRange;
  current_debt: number;
  current_finding_count: number;
  projected_score: ScoreRange;
  projected_debt: number;
  projected_finding_count: number | null;
  direction: ProjectionDirection;
  confidence: ProjectionConfidence;
  confidence_band: string;
  history_length: number;
  risk_velocity_score_per_scan: number | null;
  risk_velocity_debt_per_scan: number | null;
  finding_resolution_velocity: number | null;
  new_finding_velocity: number | null;
  hotspot_persistence_rate: number | null;
  signals: ApiProjectionSignal[];
  explanation: string;
  projected_start_index: number;
  historical_scores: ScoreRange[];
  historical_debt: number[];
  historical_scan_ids: string[];
  historical_scanned_at: string[];
  projected_endpoint_score: ScoreRange;
  projected_endpoint_debt: number;
  projected_endpoint_label: string;
}

export interface ApiScanStage {
  index: number;
  name: string;
  started_at_offset_ms: number;
  finished_at_offset_ms: number;
  duration_ms: number;
  status: 'success' | 'warning' | 'error' | 'info';
  detail: string | null;
}

export interface ApiScanStagesResponse {
  scan_id: string;
  repository_id: string;
  stages: ApiScanStage[];
}

export interface ApiAnalyzerMeta {
  analyzer_id: string;
  name: string;
  category: string;
  threshold: number | null;
}

export interface ApiAnalyzersResponse {
  count: number;
  analyzers: ApiAnalyzerMeta[];
}

export interface ApiHealthResponse {
  status: string;
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly detail: unknown;

  constructor(message: string, status: number, url: string, detail: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
    this.detail = detail;
  }
}

// ---------------------------------------------------------------------------
// Low-level fetcher
// ---------------------------------------------------------------------------

interface FetcherOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

function buildQuery(
  query: FetcherOptions['query'] | undefined
): string {
  if (!query) return '';
  const parts: string[] = [];
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length === 0 ? '' : `?${parts.join('&')}`;
}

async function request<T>(path: string, opts: FetcherOptions = {}): Promise<T> {
  const url = `${API_BASE_URL}${path}${buildQuery(opts.query)}`;
  const init: RequestInit = {
    method: opts.method ?? 'GET',
    headers: {
      Accept: 'application/json',
      ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  };

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : 'Network request failed';
    throw new ApiError(
      `Network request failed: ${detail}`,
      0,
      url,
      detail
    );
  }

  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      try {
        detail = await res.text();
      } catch {
        detail = null;
      }
    }
    throw new ApiError(
      `HTTP ${res.status} ${res.statusText} for ${path}`,
      res.status,
      url,
      detail
    );
  }

  // 204 / empty body
  if (res.status === 204) {
    return undefined as T;
  }

  try {
    return (await res.json()) as T;
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : 'Failed to parse JSON';
    throw new ApiError(
      `Invalid JSON response from ${path}: ${detail}`,
      res.status,
      url,
      detail
    );
  }
}

// ---------------------------------------------------------------------------
// Typed endpoint wrappers — one per backend endpoint, no mock fallbacks.
// ---------------------------------------------------------------------------

export function getHealth(signal?: AbortSignal): Promise<ApiHealthResponse> {
  return request<ApiHealthResponse>('/health', { signal });
}

export function getAnalyzers(
  signal?: AbortSignal
): Promise<ApiAnalyzersResponse> {
  return request<ApiAnalyzersResponse>('/api/analyzers', { signal });
}

export function postScan(
  repoPath: string,
  signal?: AbortSignal
): Promise<ApiScanResponse> {
  return request<ApiScanResponse>('/api/scan', {
    method: 'POST',
    body: { repo_path: repoPath },
    signal,
  });
}

export function getHotspots(
  repoPath: string,
  limit = 50,
  signal?: AbortSignal
): Promise<ApiHotspotResult> {
  return request<ApiHotspotResult>('/api/hotspots', {
    query: { repo_path: repoPath, limit },
    signal,
  });
}

export function getHistoryList(
  repositoryId?: string,
  limit = 50,
  signal?: AbortSignal
): Promise<ApiHistoryListResponse> {
  return request<ApiHistoryListResponse>('/api/history/list', {
    query: { repository_id: repositoryId, limit },
    signal,
  });
}

export function getHistoryLatest(
  repoPath: string,
  signal?: AbortSignal
): Promise<ApiScanRecord> {
  return request<ApiScanRecord>('/api/history/latest', {
    query: { repo_path: repoPath },
    signal,
  });
}

export function getHistoryById(
  scanId: string,
  signal?: AbortSignal
): Promise<ApiScanRecord> {
  return request<ApiScanRecord>(`/api/history/${encodeURIComponent(scanId)}`, {
    signal,
  });
}

export function getDrift(
  repoPath: string,
  fromScanId?: string,
  toScanId?: string,
  signal?: AbortSignal
): Promise<ApiDriftResult> {
  return request<ApiDriftResult>('/api/drift', {
    query: {
      repo_path: repoPath,
      from_scan_id: fromScanId,
      to_scan_id: toScanId,
    },
    signal,
  });
}

export function getTelemetryLatest(
  repoPath: string,
  signal?: AbortSignal
): Promise<ApiTelemetrySnapshot> {
  return request<ApiTelemetrySnapshot>('/api/telemetry/latest', {
    query: { repo_path: repoPath },
    signal,
  });
}

export function getTelemetryHistory(
  repoPath: string,
  limit = 50,
  signal?: AbortSignal
): Promise<ApiTelemetryHistoryResponse> {
  return request<ApiTelemetryHistoryResponse>('/api/telemetry/history', {
    query: { repo_path: repoPath, limit },
    signal,
  });
}

export function getTelemetryByScanId(
  scanId: string,
  signal?: AbortSignal
): Promise<ApiTelemetrySnapshot> {
  return request<ApiTelemetrySnapshot>(
    `/api/telemetry/scan/${encodeURIComponent(scanId)}`,
    { signal }
  );
}

export function getProjection(
  repoPath: string,
  horizon: ProjectionHorizon = 'next_scan',
  signal?: AbortSignal
): Promise<ApiRiskProjection> {
  return request<ApiRiskProjection>('/api/projection', {
    query: { repo_path: repoPath, horizon },
    signal,
  });
}

export function getScanStages(
  scanId: string,
  signal?: AbortSignal
): Promise<ApiScanStagesResponse> {
  return request<ApiScanStagesResponse>(
    `/api/scan/stages/${encodeURIComponent(scanId)}`,
    { signal }
  );
}
