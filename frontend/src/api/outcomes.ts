/**
 * outcomes — fix-log API client.
 *
 * Lists the newest-first remediation outcome records for a repository, the
 * same records Sonar writes after every guided fix run. Powers the sidebar
 * "Fixes" log so Michael can track what was fixed, when, and what moved.
 */

export interface RemediationOutcomeRecord {
  outcome_schema_version: string;
  outcome_id: string;
  repository_id: string;
  finding_id: string;
  before_scan_id: string;
  after_scan_id: string;
  attempted_at: string;
  executor: string;
  remediation_kind: string;
  build_passed: boolean | null;
  tests_passed: boolean | null;
  finding_resolved: boolean;
  finding_reintroduced: boolean;
  regression_detected: boolean;
  score_delta: number;
  debt_points_delta: number;
  successful: boolean;
}

export interface FixLogResponse {
  repository_id: string;
  outcomes: RemediationOutcomeRecord[];
  count: number;
}

async function authed(path: string): Promise<Response> {
  return fetch(path, { credentials: "include" });
}

export async function fetchFixLog(repo: string, limit = 100): Promise<FixLogResponse> {
  const params = new URLSearchParams({ repo, limit: String(limit) });
  const response = await authed(`/api/ml/remediation-outcomes?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Fix log request failed (${response.status})`);
  }
  return (await response.json()) as FixLogResponse;
}
