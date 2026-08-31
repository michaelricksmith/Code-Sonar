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
  provider_repository_id: number | null;
  provider_installation_id: number | null;
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

export interface GitHubConnectionStatus {
  configured: boolean;
  auth_mode: "oauth" | "app" | null;
  installation_id: number | null;
  token_persisted: false;
  token_exposed: false;
  managed_checkout: true;
}

export interface GitHubAppStatus {
  configured: boolean;
  webhook_configured: boolean;
  install_url: string | null;
  installation_count: number;
  tokens_persisted: false;
  tokens_exposed: false;
}

export interface GitHubInstallation {
  installation_id: number;
  account_login: string;
  account_type: string;
  installed_at: string;
  updated_at: string;
}

export interface GitHubRepository {
  repository_id: number;
  full_name: string;
  owner: string;
  name: string;
  default_branch: string;
  private: boolean;
}

const API_BASE = "/api/projects";
const GITHUB_APP_BASE = "/api/github-app";

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

export async function fetchGitHubConnectionStatus(): Promise<GitHubConnectionStatus> {
  const res = await fetch(`${API_BASE}/connect/github/status`);
  return (await decode(res, "Failed to load GitHub connection status")) as GitHubConnectionStatus;
}

export async function fetchGitHubAppStatus(): Promise<GitHubAppStatus> {
  const res = await fetch(`${GITHUB_APP_BASE}/status`);
  return (await decode(res, "Failed to load GitHub App status")) as GitHubAppStatus;
}

export async function fetchGitHubInstallations(): Promise<GitHubInstallation[]> {
  const res = await fetch(`${GITHUB_APP_BASE}/installations`);
  const data = await decode(res, "Failed to load GitHub App installations");
  return (data.installations ?? []) as GitHubInstallation[];
}

export async function activateGitHubInstallation(installationId: number): Promise<void> {
  const res = await fetch(
    `${GITHUB_APP_BASE}/installations/${encodeURIComponent(String(installationId))}/activate`,
    { method: "POST" },
  );
  await decode(res, "Failed to activate GitHub App installation");
}

export async function fetchGitHubRepositories(): Promise<GitHubRepository[]> {
  const res = await fetch(`${API_BASE}/connect/github/repositories`);
  const data = await decode(res, "Failed to load GitHub repositories");
  return (data.repositories ?? []) as GitHubRepository[];
}

export async function connectManagedGitHubProject(fullName: string): Promise<ProjectRecord> {
  const res = await fetch(`${API_BASE}/connect/github/managed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository_full_name: fullName }),
  });
  const data = await decode(res, "Failed to connect GitHub repository");
  return data.project as ProjectRecord;
}
