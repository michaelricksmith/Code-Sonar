/**
 * Prompt-first remediation API.
 *
 * The owner-facing loop: Code Sonar generates a grounded fix prompt for a
 * finding, the user copies it into their own LLM (Cursor/Claude/...), that
 * LLM changes the real repo, and Code Sonar's rescan verifies the delta.
 * The server-side auto-apply machinery is parked (backend kept, UI removed).
 */

import type { Finding } from "./analyzers";

const API_BASE = "/api/remediation";

async function decodeError(res: Response, fallback: string): Promise<Error> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail ?? fallback);
    return new Error(detail || fallback);
  } catch {
    return new Error(`${fallback} (HTTP ${res.status})`);
  }
}

function findingPayload(finding: Finding): Record<string, unknown> {
  return {
    id: finding.id,
    rule_id: finding.rule_id,
    category: finding.category,
    severity: finding.severity,
    file_path: finding.file_path,
    line_start: finding.line_start,
    line_end: finding.line_end,
    symbol: finding.symbol,
    evidence: finding.evidence,
    message: finding.message,
    suggestion: finding.suggestion,
    analyzer: finding.analyzer,
  };
}

/** Generate the deterministic fix prompt for one finding. */
export async function fetchFixPrompt(
  repository: string,
  scanId: string | null,
  finding: Finding,
): Promise<string> {
  const res = await fetch(`${API_BASE}/fix-prompt`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repository,
      scan_id: scanId,
      finding: findingPayload(finding),
    }),
  });
  if (!res.ok) throw await decodeError(res, "Couldn't generate the fix prompt");
  const data = (await res.json()) as { prompt?: unknown };
  if (typeof data.prompt !== "string" || data.prompt.length === 0) {
    throw new Error("The server returned an empty fix prompt.");
  }
  return data.prompt;
}

/** Record that the user copied a fix prompt ("fix in progress"). */
export async function logPromptCopied(
  repository: string,
  scanId: string | null,
  finding: Finding,
): Promise<void> {
  const res = await fetch(`${API_BASE}/prompt-copied`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repository,
      scan_id: scanId,
      finding_id: finding.id,
      rule_id: finding.rule_id,
      file_path: finding.file_path,
      line_start: finding.line_start,
    }),
  });
  if (!res.ok) throw await decodeError(res, "Couldn't record the prompt copy");
}

export type PromptFixStatus = "in_progress" | "resolved" | "still_open";

export interface PromptStatusItem {
  finding_id: string | null;
  rule_id: string;
  file_path: string;
  line_start: number | null;
  status: PromptFixStatus;
  copied_at: string;
}

/** Copied prompts reconciled against the latest scan for a repository. */
export async function fetchPromptStatus(
  repository: string,
): Promise<PromptStatusItem[]> {
  const res = await fetch(
    `${API_BASE}/prompt-status?repository=${encodeURIComponent(repository)}`,
    { credentials: "same-origin" },
  );
  if (!res.ok) throw await decodeError(res, "Couldn't load prompt status");
  const data = (await res.json()) as { items?: unknown };
  return Array.isArray(data.items) ? (data.items as PromptStatusItem[]) : [];
}
