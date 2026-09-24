export type RemediationRisk = "low" | "medium" | "high" | "critical";

export interface AskSonarStatus {
  configured: boolean;
  provider: string | null;
  model: string | null;
  network_checked: false;
  remediation_planning_available: boolean;
}

export interface GroundedAnswerResponse {
  scan_id: string;
  question: string;
  deterministic_score: number;
  deterministic_grade: string;
  deterministic_score_unchanged: true;
  answer: {
    answer: string;
    used_sources: string[];
    provider_name: string;
    model_name: string;
  };
  grounding: {
    context_schema_version: string;
    allowed_sources: string[];
    source_policy: {
      deterministic_is_authoritative: boolean;
      ml_is_advisory: boolean;
      never_infer_missing_repository_facts: boolean;
    };
  };
}

export interface RemediationPlan {
  plan_schema_version: string;
  plan_id: string;
  scan_id: string;
  repository_id: string;
  finding_id: string;
  rule_id: string;
  category: string;
  severity: string;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  summary: string;
  rationale: string;
  instruction: string;
  expected_files: string[];
  risk_level: RemediationRisk;
  validation_required: boolean;
  approval_required: boolean;
  expected_score_impact: null;
  deterministic_score_authority: "code_sonar";
}

export interface RemediationPlanResponse {
  plan: RemediationPlan;
  approval: {
    required: true;
    approved: false;
    execution_performed: false;
  };
  deterministic_score: number;
  deterministic_grade: string;
  deterministic_score_unchanged: true;
}

export interface AiProvider {
  name: string;
  label: string;
  configured: boolean;
  /** "env" (server-configured) | "byok" (bring your own key) | other source label */
  source: string;
}

export interface RemediationValidationResult {  before_scan_id: string;
  after_scan_id: string;
  finding_resolved: boolean;
  regression_detected: boolean;
  score_delta: number;
  debt_points_delta: number;
  build_passed: boolean | null;
  tests_passed: boolean | null;
  training_label_value: string;
  training_label_trust_tier: string;
}

export interface RemediationWorkflow {
  request_id: string;
  completed: boolean;
  stopped_at: string | null;
  active_checkout_modified: false;
  deterministic_score_authority: "code_sonar";
  execution: {
    executor_name: string;
    state: string;
    changed_files: string[];
    message: string | null;
  } | null;
  validation: RemediationValidationResult | null;
}

export interface ApproveRemediationResponse {
  plan: RemediationPlan;
  approval: {
    required: true;
    approved: true;
    request_id: string;
  };
  workflow: RemediationWorkflow;
  deterministic_score_authority: "code_sonar";
}

const API_BASE = "/api/ask-sonar";

async function decodeError(res: Response, fallback: string): Promise<Error> {
  try {
    const data = await res.json();
    const detail = data?.detail;
    if (typeof detail === "string") return new Error(detail);
    if (detail && typeof detail.message === "string") return new Error(detail.message);
  } catch {
    // Fall through to the stable fallback below.
  }
  return new Error(`${fallback} (HTTP ${res.status})`);
}

export async function fetchAskSonarStatus(): Promise<AskSonarStatus> {
  const res = await fetch(`${API_BASE}/status`, { credentials: "same-origin" });
  if (!res.ok) throw await decodeError(res, "Failed to read Ask Sonar status");
  return (await res.json()) as AskSonarStatus;
}

export async function fetchAiProviders(): Promise<AiProvider[]> {
  const res = await fetch(`${API_BASE}/providers`, { credentials: "same-origin" });
  if (!res.ok) throw await decodeError(res, "Failed to read AI providers");
  const data = await res.json();
  return (data.providers ?? data ?? []) as AiProvider[];
}

export async function askSonar(
  input: {
    scanId: string;
    question: string;
    topFindingsLimit?: number;
    similarLimit?: number;
  },
  opts: { provider?: string; apiKey?: string } = {},
): Promise<GroundedAnswerResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.provider) headers["X-AI-Provider"] = opts.provider;
  if (opts.apiKey) headers["X-AI-API-Key"] = opts.apiKey;
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify({
      scan_id: input.scanId,
      question: input.question,
      task: "debt_risk",
      top_findings_limit: input.topFindingsLimit ?? 10,
      similar_limit: input.similarLimit ?? 3,
    }),
  });
  if (!res.ok) throw await decodeError(res, "Ask Sonar could not answer");
  return (await res.json()) as GroundedAnswerResponse;
}

export async function fetchRemediationPlan(
  scanId: string,
  findingId: string,
): Promise<RemediationPlanResponse> {
  const res = await fetch(
    `${API_BASE}/remediation-plan/${encodeURIComponent(scanId)}/${encodeURIComponent(findingId)}`,
    { credentials: "same-origin" },
  );
  if (!res.ok) throw await decodeError(res, "Failed to build remediation plan");
  return (await res.json()) as RemediationPlanResponse;
}

export async function approveAndRunRemediation(input: {
  requestId: string;
  scanId: string;
  findingId: string;
  planId: string;
}): Promise<ApproveRemediationResponse> {
  const res = await fetch(`${API_BASE}/remediation/approve-and-run`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      request_id: input.requestId,
      scan_id: input.scanId,
      finding_id: input.findingId,
      plan_id: input.planId,
      approved: true,
    }),
  });
  if (!res.ok) throw await decodeError(res, "Remediation workflow failed");
  return (await res.json()) as ApproveRemediationResponse;
}
