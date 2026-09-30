/**
 * PricingView — plan comparison + Stripe checkout entry point.
 *
 * Public route (#/pricing): signed-out visitors see the tiers with a
 * "Sign in to upgrade" nudge; signed-in users see their current plan,
 * upgrade buttons (Stripe Checkout), and "Manage billing" for paid plans.
 * When Stripe isn't configured server-side (503 billing_disabled), upgrade
 * buttons are replaced with a friendly notice instead of a broken flow.
 */

import { useEffect, useState } from "react";

import type { User } from "../api/auth";
import { GITHUB_LOGIN_URL } from "../api/auth";
import {
  BILLING_TIERS,
  PENDING_CHECKOUT_TIER_KEY,
  cancelSubscription,
  createCheckout,
  fetchSubscriptionState,
  isBillingDisabledError,
  isCheckoutTier,
  isPaidPlan,
  openPortal,
  resumeSubscription,
} from "../api/billing";
import { assertBillingUrl } from "../utils/security";
import type { BillingPlan, BillingStatus, CheckoutTier, SubscriptionState } from "../api/billing";
import { SiteFooter } from "./SiteFooter";

interface PricingViewProps {
  user: User | null;
  billing: BillingStatus | null;
  billingLoading: boolean;
}

function tierLabel(plan: BillingPlan): string {
  return plan === "free" ? "Free" : plan === "hobby" ? "Hobby" : "Plus";
}

function tierMonthlyPrice(tier: CheckoutTier): string {
  return tier === "hobby" ? "$7" : "$14";
}

/** Plain-language auto-renew disclosure, shown on the card itself — never
 *  behind a link or tooltip. */
function disclosureText(tier: CheckoutTier): string {
  return (
    `${tierMonthlyPrice(tier)}/month, billed monthly. Renews automatically ` +
    `each month until you cancel. Cancel anytime from your billing settings — no calls, no emails.`
  );
}

function formatPeriodEnd(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function PricingView({ user, billing, billingLoading }: PricingViewProps) {
  const [checkingOut, setCheckingOut] = useState<CheckoutTier | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [billingDisabled, setBillingDisabled] = useState(false);
  /** Explicit, unchecked-by-default auto-renew consent per paid tier. */
  const [consent, setConsent] = useState<Record<CheckoutTier, boolean>>({ hobby: false, plus: false });
  /** Subscription detail state for the in-app Subscription panel. */
  const [subState, setSubState] = useState<SubscriptionState | null>(null);
  const [subLoading, setSubLoading] = useState(false);
  const [subError, setSubError] = useState<string | null>(null);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [subActionLoading, setSubActionLoading] = useState(false);

  const plan: BillingPlan | null = billing?.plan ?? null;
  const paidUser = !!user && isPaidPlan(plan);

  const refreshSubscription = async (): Promise<void> => {
    setSubLoading(true);
    setSubError(null);
    try {
      setSubState(await fetchSubscriptionState());
    } catch (e) {
      setSubError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubLoading(false);
    }
  };

  useEffect(() => {
    if (!paidUser) {
      setSubState(null);
      return;
    }
    void refreshSubscription();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paidUser]);

  /**
   * Resume a checkout that was interrupted by sign-in: the visitor clicked
   * a paid tier while signed out, went through OAuth (which always lands
   * on /app), and was routed back here. We don't start Stripe Checkout
   * automatically — checkout needs the explicit auto-renew consent box,
   * which the visitor never saw while signed out — so we point them at it
   * with a notice instead.
   */
  useEffect(() => {
    if (!user || billingLoading) return;
    let pending: string | null = null;
    try {
      pending = window.sessionStorage.getItem(PENDING_CHECKOUT_TIER_KEY);
    } catch {
      return;
    }
    if (!isCheckoutTier(pending)) return;
    // Wait for billing status before deciding: billing starts null with
    // loading=false on first paint, and consuming the key before the plan
    // is known would silently drop the checkout. The key stays put until
    // the plan is known, so a slow billing fetch can't swallow it.
    if (billing === null) return;
    try {
      window.sessionStorage.removeItem(PENDING_CHECKOUT_TIER_KEY);
    } catch {
      // best-effort
    }
    // Already on a paid plan: nothing to buy, just show the tiers.
    if (billing.plan !== "free") return;
    // The visitor clicked "Sign in to upgrade" before signing in. We don't
    // auto-start checkout here: checkout requires the explicit,
    // unchecked-by-default billing consent box, so we point them at it
    // instead of asserting consent they never gave.
    setNotice(
      `Welcome back — tick the billing consent box under ${tierLabel(pending)} to finish your upgrade.`,
    );
  }, [user, billingLoading, billing]);

  async function handleUpgrade(tier: CheckoutTier, autorenewConsent: boolean): Promise<void> {
    setNotice(null);
    setCheckingOut(tier);
    try {
      // An explicit upgrade click supersedes any remembered one.
      window.sessionStorage.removeItem(PENDING_CHECKOUT_TIER_KEY);
    } catch {
      // best-effort
    }
    try {
      window.location.href = assertBillingUrl(await createCheckout(tier, autorenewConsent));
    } catch (e) {
      if (isBillingDisabledError(e)) {
        setBillingDisabled(true);
        setNotice("Billing isn't enabled yet — paid plans are coming soon. Your Free plan keeps working in the meantime.");
      } else {
        setNotice(e instanceof Error ? e.message : String(e));
      }
      setCheckingOut(null);
    }
  }

  async function handleManageBilling(): Promise<void> {
    setNotice(null);
    setPortalLoading(true);
    try {
      window.location.href = assertBillingUrl(await openPortal());
    } catch (e) {
      if (isBillingDisabledError(e)) {
        setBillingDisabled(true);
        setNotice("Billing isn't enabled yet — the billing portal is coming soon.");
      } else {
        setNotice(e instanceof Error ? e.message : String(e));
      }
      setPortalLoading(false);
    }
  }

  async function handleCancelSubscription(): Promise<void> {
    setSubActionLoading(true);
    setSubError(null);
    try {
      await cancelSubscription();
      setConfirmingCancel(false);
      await refreshSubscription();
    } catch (e) {
      setSubError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubActionLoading(false);
    }
  }

  async function handleResumeSubscription(): Promise<void> {
    setSubActionLoading(true);
    setSubError(null);
    try {
      await resumeSubscription();
      await refreshSubscription();
    } catch (e) {
      setSubError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubActionLoading(false);
    }
  }

  return (
    <div className="page">
      {!user && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 26 }}>
          <a className="brand" href="#/">
            <span className="brand-mark" />
            Code&nbsp;Sonar
          </a>
          <a className="btn btn-ghost btn-sm" href={GITHUB_LOGIN_URL}>Sign in</a>
        </div>
      )}

      <h1 className="page-title">Pick the plan that fits your shipping</h1>
      <p className="page-sub">
        {user
          ? `Signed in as ${user.name} — upgrade anytime, or cancel in one tap from the Subscription panel below (no calls, no emails). You can also manage billing in the Stripe customer portal.`
          : "Start free, upgrade when your repo (or your curiosity) outgrows it."}
      </p>

      {billingLoading && user && (
        <div className="notice warning" style={{ marginTop: 18 }}>
          Checking your current plan…
        </div>
      )}

      {notice && (
        <div className="notice warning" style={{ marginTop: 18 }}>
          <b>Billing</b>
          {notice}
        </div>
      )}

      {paidUser && (
        <section className="card sub-panel" aria-label="Subscription" style={{ marginTop: 22 }}>
          <h2 className="sub-panel-title">Subscription</h2>
          {subLoading && !subState && <p className="sub-panel-status">Loading your subscription…</p>}
          {subError && (
            <div className="notice danger" style={{ marginBottom: 12 }}>
              <b>Subscription</b>
              {subError}
              <div style={{ marginTop: 10 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => void refreshSubscription()}>
                  Try again
                </button>
              </div>
            </div>
          )}
          {subState && (
            <>
              <p className="sub-panel-status">
                <b>{tierLabel(subState.plan)}</b>
                {" · "}
                {subState.cancel_at_period_end
                  ? `Cancelling — your plan stays active until ${formatPeriodEnd(subState.current_period_end)}.`
                  : subState.current_period_end
                    ? `Renews on ${formatPeriodEnd(subState.current_period_end)}.`
                    : "Active."}
              </p>

              {!confirmingCancel && !subState.cancel_at_period_end && (
                <button
                  className="btn btn-ghost sub-cancel-btn"
                  onClick={() => setConfirmingCancel(true)}
                  disabled={subActionLoading}
                >
                  Cancel subscription
                </button>
              )}

              {confirmingCancel && (
                <div className="cancel-confirm" role="alertdialog" aria-label="Confirm subscription cancellation">
                  <p>
                    Cancel my subscription? You&rsquo;ll keep {tierLabel(plan as BillingPlan)} until{" "}
                    {formatPeriodEnd(subState.current_period_end)}.
                  </p>
                  <div className="cancel-confirm-actions">
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => void handleCancelSubscription()}
                      disabled={subActionLoading}
                    >
                      {subActionLoading ? "Cancelling…" : "Yes, cancel"}
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => setConfirmingCancel(false)}
                      disabled={subActionLoading}
                    >
                      Keep my plan
                    </button>
                  </div>
                </div>
              )}

              {subState.cancel_at_period_end && (
                <button
                  className="btn btn-primary sub-cancel-btn"
                  onClick={() => void handleResumeSubscription()}
                  disabled={subActionLoading}
                >
                  {subActionLoading ? "Working…" : "Keep my plan"}
                </button>
              )}

              <div className="sub-portal-link">
                or manage in the{" "}
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => void handleManageBilling()}
                  disabled={portalLoading || billingDisabled}
                >
                  {portalLoading ? "Opening…" : "Stripe customer portal"}
                </button>
              </div>
            </>
          )}
        </section>
      )}

      <div className="cards pricing-grid">
        {BILLING_TIERS.map((tier) => {
          const isCurrent = plan === tier.tier;
          const isPaid = tier.tier !== "free";
          const popular = tier.tier === "hobby";
          return (
            <div key={tier.tier} className={`card pricing-card${popular ? " pricing-popular" : ""}`}>
              {popular && <div className="pricing-flag">Most popular</div>}
              {isCurrent && <div className="pricing-current">Current plan</div>}
              <h3>{tier.name}</h3>
              <div className="pricing-price">
                {tier.price}
                <span>{tier.tier === "free" ? " forever" : " / month"}</span>
              </div>
              <p className="pricing-tagline">{tier.tagline}</p>
              <ul className="pricing-features">
                {tier.features.map((f) => (
                  <li key={f}>
                    <span className="pricing-check">✓</span>
                    {f}
                  </li>
                ))}
              </ul>

              {isCurrent ? (
                isPaidPlan(plan) ? (
                  <button
                    className="btn btn-ghost"
                    style={{ width: "100%" }}
                    onClick={() => void handleManageBilling()}
                    disabled={portalLoading || billingDisabled}
                  >
                    {portalLoading ? "Opening…" : "Manage billing"}
                  </button>
                ) : (
                  <button className="btn btn-ghost" style={{ width: "100%" }} disabled>
                    You&rsquo;re on Free
                  </button>
                )
              ) : isPaid ? (
                !user ? (
                  <>
                    <p className="billing-disclosure">{disclosureText(tier.tier as CheckoutTier)}</p>
                    <a
                      className="btn btn-primary"
                      style={{ width: "100%" }}
                      href={GITHUB_LOGIN_URL}
                      onClick={() => {
                        // Remember the click across the OAuth round-trip so
                        // sign-in returns here and resumes this checkout.
                        try {
                          window.sessionStorage.setItem(
                            PENDING_CHECKOUT_TIER_KEY,
                            tier.tier,
                          );
                        } catch {
                          // best-effort; without it the visitor just lands on /app
                        }
                      }}
                    >
                      Sign in to upgrade
                    </a>
                  </>
                ) : billingDisabled ? (
                  <>
                    <p className="billing-disclosure">{disclosureText(tier.tier as CheckoutTier)}</p>
                    <button className="btn btn-primary" style={{ width: "100%" }} disabled title="Billing isn't enabled yet">
                      Upgrade to {tierLabel(tier.tier)}
                    </button>
                  </>
                ) : (
                  <>
                    <p className="billing-disclosure">{disclosureText(tier.tier as CheckoutTier)}</p>
                    <label className="consent-check">
                      <input
                        type="checkbox"
                        checked={consent[tier.tier as CheckoutTier]}
                        onChange={(e) =>
                          setConsent((c) => ({ ...c, [tier.tier]: e.target.checked }))
                        }
                      />
                      <span>
                        I agree to be billed {tierMonthlyPrice(tier.tier as CheckoutTier)}/month automatically until I cancel.
                      </span>
                    </label>
                    <button
                      className={`btn ${popular ? "btn-primary" : "btn-ghost"}`}
                      style={{ width: "100%" }}
                      onClick={() => void handleUpgrade(tier.tier as CheckoutTier, consent[tier.tier as CheckoutTier])}
                      disabled={checkingOut !== null || !consent[tier.tier as CheckoutTier]}
                      title={consent[tier.tier as CheckoutTier] ? undefined : "Tick the consent box above to upgrade"}
                    >
                      {checkingOut === tier.tier ? "Starting checkout…" : `Upgrade to ${tierLabel(tier.tier)}`}
                    </button>
                  </>
                )
              ) : (
                /* Free card viewed by a paid user: nothing to buy here. */
                user && plan !== "free" ? (
                  <button className="btn btn-ghost" style={{ width: "100%" }} disabled>
                    Included in {tierLabel(plan as BillingPlan)}
                  </button>
                ) : null
              )}
            </div>
          );
        })}
      </div>

      <p className="page-sub" style={{ marginTop: 26, fontSize: 13.5 }}>
        Payments are processed securely by Stripe. Prices in USD. Cancel anytime —
        you keep your plan until the end of the billing period.
      </p>

      <SiteFooter />
    </div>
  );
}
