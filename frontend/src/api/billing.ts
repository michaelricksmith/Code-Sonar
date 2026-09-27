/**
 * Code Sonar — Stripe billing API client (test-mode ready).
 *
 * Backend contract:
 *   POST /api/billing/checkout {"tier": "hobby"|"plus"} → {"checkout_url"}
 *   POST /api/billing/portal                    → {"portal_url"}
 *   GET  /api/billing/status                    →
 *     {"plan": "free"|"hobby"|"plus",
 *      "limits": {"repos","scans_per_month","ask_sonar_per_month","history_days","priority"},
 *      "usage":  {"scans_used","ask_sonar_used","period_start"}}
 *
 * Quota: any API call may answer 402 with
 *   {"upgrade_required": true, "kind": "scans"|"ask_sonar", "plan", "limit", "used"}.
 * All fetches here throw ApiError (status + body attached) on failure.
 */

import { ApiError, decodeOrThrow } from "./errors";

export type BillingPlan = "free" | "hobby" | "plus";
export type CheckoutTier = "hobby" | "plus";

export interface BillingLimits {
  repos: number;
  scans_per_month: number;
  ask_sonar_per_month: number;
  /** null = unlimited history */
  history_days: number | null;
  priority: boolean;
}

export interface BillingUsage {
  scans_used: number;
  ask_sonar_used: number;
  period_start: string;
}

export interface BillingStatus {
  plan: BillingPlan;
  limits: BillingLimits;
  usage: BillingUsage;
}

export interface BillingTierInfo {
  tier: BillingPlan;
  name: string;
  price: string;
  tagline: string;
  features: string[];
}

/** Exact tier content shown on the pricing page. */
export const BILLING_TIERS: BillingTierInfo[] = [
  {
    tier: "free",
    name: "Free",
    price: "$0",
    tagline: "Get your first score, free forever.",
    features: [
      "1 repo",
      "5 scans / month",
      "Unlimited fix prompts",
      "25 Ask Sonar questions / month",
      "7-day scan history",
    ],
  },
  {
    tier: "hobby",
    name: "Hobby",
    price: "$7/mo",
    tagline: "For builders shipping side projects.",
    features: [
      "5 repos",
      "50 scans / month",
      "Unlimited fix prompts",
      "500 Ask Sonar questions / month",
      "90-day history with score deltas + verified-fixed tracking",
    ],
  },
  {
    tier: "plus",
    name: "Plus",
    price: "$14/mo",
    tagline: "For pros who want it all.",
    features: [
      "20 repos",
      "300 scans / month",
      "Unlimited fix prompts",
      "2,000 Ask Sonar questions / month",
      "Unlimited history",
      "Priority scan queue",
    ],
  },
];

export function isPaidPlan(plan: BillingPlan | null | undefined): boolean {
  return plan === "hobby" || plan === "plus";
}

/**
 * True when the failure means Stripe isn't configured server-side
 * (503 {"billing_disabled": true}).
 */
export function isBillingDisabledError(e: unknown): boolean {
  if (!(e instanceof ApiError) || e.status !== 503) return false;
  const body = e.body as { billing_disabled?: boolean } | null;
  return !!body && body.billing_disabled === true;
}

const jsonHeaders = { "Content-Type": "application/json" };

export async function fetchBillingStatus(): Promise<BillingStatus> {
  const res = await fetch("/api/billing/status", { credentials: "same-origin" });
  return (await decodeOrThrow(res, "Could not load billing status")) as BillingStatus;
}

/**
 * Starts a Stripe Checkout session for the tier and returns the URL to
 * redirect the browser to. Throws ApiError with status 503 when billing
 * isn't enabled yet, 400 for an unknown tier, 401 when signed out.
 */
export async function createCheckout(tier: CheckoutTier): Promise<string> {
  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
    body: JSON.stringify({ tier }),
  });
  const data = await decodeOrThrow(res, "Could not start checkout");
  if (typeof data?.checkout_url !== "string" || !data.checkout_url) {
    throw new Error("Checkout started but returned no redirect URL.");
  }
  return data.checkout_url as string;
}

/**
 * Returns the Stripe Customer Portal URL to redirect the browser to.
 * Throws ApiError 400 when the user has no Stripe customer yet.
 */
export async function openPortal(): Promise<string> {
  const res = await fetch("/api/billing/portal", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
  });
  const data = await decodeOrThrow(res, "Could not open the billing portal");
  if (typeof data?.portal_url !== "string" || !data.portal_url) {
    throw new Error("Billing portal returned no redirect URL.");
  }
  return data.portal_url as string;
}
