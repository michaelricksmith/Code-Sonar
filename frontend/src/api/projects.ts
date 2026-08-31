import type { DriftResult, ScanResponse } from "./analyzers";

export interface ProjectRecord {
  project_id: string;
  provider: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  connected_at: string;
  latest_scan_id: string | null;
  latest_score: number | null;
}

export interface ProjectHistorySummary {
  scan_id: string;
  repository_id: string;
  scanned_at: string;
  schema_version: string;
  score: number;
  grade: string;
  total_debt_points: number;
  finding_count: number;
  category_scores: Record<string, number>;
  severity_distribution: Record<string, number>;
  findings_by_category: Record<string, number>;
  findings_source_breakdown: Record<string, number>;
}

export interface ProjectDashboard {
  project: ProjectRecord;
  latest_scan: (ProjectHistorySummary & { findings: ScanResponse["findings"] }) | null;
  history: ProjectHistorySummary[];
  history_count: number;
  local_checkout_path_exposed: false;
  deterministic_score_authority: "code_sonar";
}

const API_BASE = "/api/projects";

async function decode(res: Response, fallback: string): Promise<any> {
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail ?? `${fallback} (HTTP ${res.status})`);
  return data;
}

export async function fetchProjects(): Promise<ProjectRecord[]> {
  const res = await fetch(API_BASE);
  const data = await decode(res, "Failed to load projects");
  return (data.projects ?? []) as ProjectRecord[];
}

export async function fetchProjectDashboard(projectId: string): Promise<ProjectDashboard> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(projectId)}/dashboard`);
  return (await decode(res, "Failed to load project dashboard")) as ProjectDashboard;
}

export async function scanProject(projectId: string): Promise<ScanResponse> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(projectId)}/scan`, { method: "POST" });
  return (await decode(res, "Project scan failed")) as ScanResponse;
}

export async function fetchProjectDrift(projectId: string): Promise<DriftResult> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(projectId)}/drift`);
  return (await decode(res, "Project drift failed")) as DriftResult;
}
