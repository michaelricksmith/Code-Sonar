/**
 * Code Sonar — Stripe billing API client (test-mode ready).
 *
 * Backend contract:
 *   POST /api/billing/checkout {"tier": "hobby"|"plus", "autorenew_consent": true}
 *     → {"checkout_url"} (400 when autorenew_consent is not true)
 *   POST /api/billing/portal                    → {"portal_url"}
 *   POST /api/billing/cancel                    → {"cancelled": true, "effective_at", "plan"}
 *   POST /api/billing/resume                    → {"resumed": true}
 *   GET  /api/billing/subscription               →
 *     {"active": bool, "plan": "free"|"hobby"|"plus",
 *      "status": "active"|"canceled"|"none",
 *      "cancel_at_period_end": bool,
 *      "current_period_end": string|null (ISO),
 *      "stripe_subscription_id": string|null}
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

/**
 * sessionStorage key remembering which paid tier a signed-out visitor
 * clicked. The OAuth callback always lands on /app, so after sign-in the
 * app reads this key, returns to #/pricing, and resumes the checkout the
 * visitor originally asked for.
 */
export const PENDING_CHECKOUT_TIER_KEY = "code_sonar_pending_checkout_tier";

export function isCheckoutTier(value: unknown): value is CheckoutTier {
  return value === "hobby" || value === "plus";
}

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
 * redirect the browser to. The caller must pass the user's explicit
 * auto-renew consent (the unchecked-by-default checkbox on the pricing
 * page); the backend answers 400 when autorenew_consent is not true.
 * Throws ApiError with status 503 when billing isn't enabled yet, 400
 * for an unknown tier, 401 when signed out.
 */
export async function createCheckout(tier: CheckoutTier, autorenewConsent: boolean): Promise<string> {
  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
    body: JSON.stringify({ tier, autorenew_consent: autorenewConsent }),
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

/** The user's current subscription state (always 200, even with no subscription). */
export interface SubscriptionState {
  active: boolean;
  plan: BillingPlan;
  status: "active" | "canceled" | "none";
  cancel_at_period_end: boolean;
  /** ISO timestamp of the current period end, or null when unknown. */
  current_period_end: string | null;
  stripe_subscription_id: string | null;
}

export async function fetchSubscriptionState(): Promise<SubscriptionState> {
  const res = await fetch("/api/billing/subscription", { credentials: "same-origin" });
  return (await decodeOrThrow(res, "Could not load subscription details")) as SubscriptionState;
}

export interface CancelSubscriptionResult {
  cancelled: boolean;
  /** ISO timestamp when the cancellation takes effect (end of period). */
  effective_at: string;
  plan: string;
}

/**
 * Cancels the active subscription at the end of the current billing
 * period. Throws ApiError 400 {"detail": "no active subscription"} when
 * there is nothing to cancel.
 */
export async function cancelSubscription(): Promise<CancelSubscriptionResult> {
  const res = await fetch("/api/billing/cancel", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
  });
  return (await decodeOrThrow(res, "Could not cancel the subscription")) as CancelSubscriptionResult;
}

/** Reverses a scheduled cancellation ("Keep my plan"). */
export async function resumeSubscription(): Promise<{ resumed: boolean }> {
  const res = await fetch("/api/billing/resume", {
    method: "POST",
    headers: jsonHeaders,
    credentials: "same-origin",
  });
  return (await decodeOrThrow(res, "Could not resume the subscription")) as { resumed: boolean };
}
