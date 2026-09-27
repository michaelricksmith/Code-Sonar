/**
 * PricingView — plan comparison + Stripe checkout entry point.
 *
 * Public route (#/pricing): signed-out visitors see the tiers with a
 * "Sign in to upgrade" nudge; signed-in users see their current plan,
 * upgrade buttons (Stripe Checkout), and "Manage billing" for paid plans.
 * When Stripe isn't configured server-side (503 billing_disabled), upgrade
 * buttons are replaced with a friendly notice instead of a broken flow.
 */

import { useState } from "react";

import type { User } from "../api/auth";
import { GITHUB_LOGIN_URL } from "../api/auth";
import {
  BILLING_TIERS,
  createCheckout,
  isBillingDisabledError,
  isPaidPlan,
  openPortal,
} from "../api/billing";
import type { BillingPlan, BillingStatus, CheckoutTier } from "../api/billing";

interface PricingViewProps {
  user: User | null;
  billing: BillingStatus | null;
  billingLoading: boolean;
}

function tierLabel(plan: BillingPlan): string {
  return plan === "free" ? "Free" : plan === "hobby" ? "Hobby" : "Plus";
}

export function PricingView({ user, billing, billingLoading }: PricingViewProps) {
  const [checkingOut, setCheckingOut] = useState<CheckoutTier | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [billingDisabled, setBillingDisabled] = useState(false);

  const plan: BillingPlan | null = billing?.plan ?? null;

  async function handleUpgrade(tier: CheckoutTier): Promise<void> {
    setNotice(null);
    setCheckingOut(tier);
    try {
      window.location.href = await createCheckout(tier);
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
      window.location.href = await openPortal();
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
          ? `Signed in as ${user.name} — upgrade, downgrade, or cancel anytime from the billing portal.`
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
                  <a className="btn btn-primary" style={{ width: "100%" }} href={GITHUB_LOGIN_URL}>
                    Sign in to upgrade
                  </a>
                ) : billingDisabled ? (
                  <button className="btn btn-primary" style={{ width: "100%" }} disabled title="Billing isn't enabled yet">
                    Upgrade to {tierLabel(tier.tier)}
                  </button>
                ) : (
                  <button
                    className={`btn ${popular ? "btn-primary" : "btn-ghost"}`}
                    style={{ width: "100%" }}
                    onClick={() => void handleUpgrade(tier.tier as CheckoutTier)}
                    disabled={checkingOut !== null}
                  >
                    {checkingOut === tier.tier ? "Starting checkout…" : `Upgrade to ${tierLabel(tier.tier)}`}
                  </button>
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
    </div>
  );
}
