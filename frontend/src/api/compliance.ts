/**
 * Code Sonar — pre-launch compliance API client.
 *
 * Backend contract (same-origin, cookie auth):
 *   GET  /api/compliance/status            → {"age_gate_completed", "marketing_opt_in", "gpc_honored"}
 *   POST /api/compliance/age-gate {"birth_year": int}
 *     → 200 {"ok": true, "bracket": "13-17"|"18+"}
 *     → 403 {"detail": {"blocked": true, "reason": "under_13"}}
 *   POST /api/compliance/age-gate/block    → {"scrubbed": true}
 *   POST /api/compliance/marketing-consent {"opt_in": bool} → {"opt_in": bool}
 *   POST /api/compliance/gpc {"gpc": true} → {"honored": true}
 *
 * All fetches throw ApiError (status + body attached) on failure, via the
 * shared decodeOrThrow helper.
 */

import { ApiError, decodeOrThrow } from "./errors";

export interface ComplianceStatus {
  age_gate_completed: boolean;
  marketing_opt_in: boolean;
  gpc_honored: boolean;
}

export type AgeBracket = "13-17" | "18+";

export interface AgeGateResult {
  ok: boolean;
  bracket: AgeBracket;
}

const jsonHeaders = { "Content-Type": "application/json" };

export async function fetchComplianceStatus(): Promise<ComplianceStatus> {
  const res = await fetch("/api/compliance/status", { credentials: "same-origin" });
  return (await decodeOrThrow(res, "Could not load compliance status")) as ComplianceStatus;
}

/**
 * Submits the user's birth year to the age gate. Resolves with the age
 * bracket on success. Throws ApiError 403 when the account is blocked
 * (under 13) — detect it with isUnderageBlockedError().
 */
export async function submitAgeGate(birthYear: number): Promise<AgeGateResult> {
  const res = await fetch("/api/compliance/age-gate", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
    body: JSON.stringify({ birth_year: birthYear }),
  });
  return (await decodeOrThrow(res, "Could not verify your age")) as AgeGateResult;
}

/** True when `e` is the under-13 blocked response from the age gate. */
export function isUnderageBlockedError(e: unknown): boolean {
  if (!(e instanceof ApiError) || e.status !== 403) return false;
  const detail = (e.body as { detail?: { blocked?: boolean } } | null)?.detail;
  return !!detail && detail.blocked === true;
}

/**
 * Scrubs the under-13 account server-side. Call this, then sign the user
 * out, then show the "13 and older" message.
 */
export async function blockUnderageAccount(): Promise<void> {
  const res = await fetch("/api/compliance/age-gate/block", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
  });
  await decodeOrThrow(res, "Could not remove the account");
}

export async function setMarketingConsent(optIn: boolean): Promise<boolean> {
  const res = await fetch("/api/compliance/marketing-consent", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
    body: JSON.stringify({ opt_in: optIn }),
  });
  const data = await decodeOrThrow(res, "Could not save your email preference");
  return data?.opt_in === true;
}

/**
 * Reports a Global Privacy Control signal. Fire-and-forget: the caller
 * should swallow errors so a GPC report never breaks the page.
 */
export async function reportGpc(): Promise<void> {
  const res = await fetch("/api/compliance/gpc", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
    body: JSON.stringify({ gpc: true }),
  });
  await decodeOrThrow(res, "Could not honor the privacy signal");
}
