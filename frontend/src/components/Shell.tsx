/**
 * Shell — the authenticated app frame: sidebar + main content.
 * Mirrors the mockup sidebar (Overview / Issues / Files, Progress).
 */

import type { ReactNode } from "react";

import type { User } from "../api/auth";
import { isPaidPlan } from "../api/billing";
import type { BillingStatus } from "../api/billing";
import { SiteFooter } from "./SiteFooter";

export type ShellView = "overview" | "issues" | "fixes" | "pricing" | "admin";

export interface PromptActivity {
  inProgress: number;
  resolved: number;
  stillOpen: number;
}

interface ShellProps {
  user: User;
  repoLabel: string | null;
  repoSub: string | null;
  view: ShellView;
  issueCount: number | null;
  fixCount: number | null;
  promptActivity: PromptActivity | null;
  onNavigate: (view: ShellView) => void;
  onSignOut: () => void;
  onOpenSonar: () => void;
  /** Re-scan the current repo; exposed in the sidebar so it's one tap away on every page. */
  onRescan: () => void;
  rescanning: boolean;
  /** Billing status for the compact plan/usage block (null while loading or signed out). */
  billing?: BillingStatus | null;
  /** Opens the Stripe customer portal; shown for paid plans. */
  onManageBilling?: () => void;
  children: ReactNode;
}

export function Shell({
  user,
  repoLabel,
  repoSub,
  view,
  issueCount,
  fixCount,
  promptActivity,
  onNavigate,
  onSignOut,
  onOpenSonar,
  onRescan,
  rescanning,
  billing,
  onManageBilling,
  children,
}: ShellProps) {
  const rescanLabel = rescanning ? "↻ Scanning…" : "↻ Re-scan";
  const paid = isPaidPlan(billing?.plan);
  return (
    <div className="shell">
      <div className="mobile-topbar">
        <a className="brand" href="#/app">
          <span className="brand-mark" />
          Code&nbsp;Sonar
        </a>
        <div style={{ display: "flex", gap: 8 }}>
          {repoLabel && (
            <button className="signout" onClick={onRescan} disabled={rescanning} title="Re-scan this repo">
              {rescanLabel}
            </button>
          )}
          <button className="signout" onClick={onSignOut} title="Sign out">Sign out</button>
        </div>
      </div>
      <aside className="sidebar" aria-label="Primary navigation">
        <div>
          <a className="brand" href="#/app">
            <span className="brand-mark" />
            Code&nbsp;Sonar
          </a>
          <div className="side-repo">
            <b>{repoLabel ?? "No repo yet"}</b>
            <span>{repoSub ?? "Pick a repo to get your first score"}</span>
          </div>
          {repoLabel && (
            <button className="side-rescan" onClick={onRescan} disabled={rescanning} title="Re-scan this repo">
              {rescanLabel}
            </button>
          )}

          <div className="side-label">Workspace</div>
          <button className={`side-item ${view === "overview" ? "active" : ""}`} onClick={() => onNavigate("overview")}>
            ◉ Overview
          </button>
          <button className={`side-item ${view === "issues" ? "active" : ""}`} onClick={() => onNavigate("issues")}>
            ⚠ Issues{issueCount != null && <span className="count">{issueCount}</span>}
          </button>

          <div className="side-label">Progress</div>
          <button className={`side-item ${view === "fixes" ? "active" : ""}`} onClick={() => onNavigate("fixes")}>
            ✓ Fixes{fixCount != null && fixCount > 0 && <span className="count">{fixCount}</span>}
          </button>
          {promptActivity != null &&
            promptActivity.inProgress + promptActivity.resolved + promptActivity.stillOpen > 0 && (
              <div className="side-detail" aria-label="Fix activity">
                {promptActivity.inProgress > 0 && (
                  <div className="side-detail-row">
                    <span>✎</span>
                    <span>{promptActivity.inProgress} prompt{promptActivity.inProgress === 1 ? "" : "s"} in progress</span>
                  </div>
                )}
                {promptActivity.resolved > 0 && (
                  <div
                    className="side-detail-row side-win"
                    style={{
                      fontWeight: 700,
                      color: "var(--good)",
                      fontSize: 14,
                    }}
                  >
                    <span>✓</span>
                    <span>{promptActivity.resolved} verified fixed</span>
                  </div>
                )}
                {promptActivity.stillOpen > 0 && (
                  <div className="side-detail-row">
                    <span>⚠</span>
                    <span>{promptActivity.stillOpen} still open</span>
                  </div>
                )}
              </div>
            )}
          <button className="side-item" onClick={onOpenSonar}>↗ History</button>

          {billing && (
            <>
              <div className="side-label">Plan</div>
              <div className="side-detail" aria-label="Plan usage">                <div className="side-detail-row">
                  <span className={`plan-badge plan-${billing.plan}`}>
                    {user.is_staff ? "Staff" : billing.plan === "free" ? "Free" : billing.plan === "hobby" ? "Hobby" : "Plus"}
                  </span>
                  {!user.is_staff && (
                    <a className="side-link" href="#/pricing" title="See plans">
                      {paid ? "Plans" : "Upgrade"}
                    </a>
                  )}
                </div>
                <div className="side-detail-row">
                  <span>◈</span>
                  <span>
                    Scans {billing.usage.scans_used}
                    {user.is_staff ? " · unlimited" : `/${billing.limits.scans_per_month}`}
                  </span>
                </div>
                <div className="side-detail-row">
                  <span>✦</span>
                  <span>
                    Ask Sonar {billing.usage.ask_sonar_used}
                    {user.is_staff ? " · unlimited" : `/${billing.limits.ask_sonar_per_month}`}
                  </span>
                </div>
                {paid && onManageBilling && (
                  <div className="side-detail-row">
                    <span>⚙</span>
                    <button className="side-link-btn" onClick={onManageBilling}>
                      Manage billing
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
          {user.is_admin && (
            <>
              <div className="side-label">Admin</div>
              <button className={`side-item ${view === "admin" ? "active" : ""}`} onClick={() => onNavigate("admin")}>
                ⚙ Console
              </button>
            </>
          )}
        </div>

        <div className="side-foot">
          <div className="user-chip" style={{ padding: "0 0 10px" }}>
            {user.avatar_url ? <img src={user.avatar_url} alt="" /> : <span className="brand-mark" style={{ width: 32, height: 32 }} />}
            <span className="who">
              <span className="who-name">
                <b title={user.name}>{user.name}</b>
                {user.is_admin && (
                  <span className="mini-badge is-admin" title="Admin access">admin</span>
                )}
                {user.is_staff && (
                  <span className="mini-badge is-staff" title="Unlimited testing quota">staff</span>
                )}
              </span>
              <span title={user.email}>{user.email}</span>
            </span>
            <button className="signout" onClick={onSignOut} title="Sign out">Sign out</button>
          </div>
          <div><span className="dot" />Sonar is watching · {repoLabel ? "repo connected" : "no repo yet"}</div>
          <SiteFooter variant="compact" />
        </div>
      </aside>

      <main className="main" id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}

/** Floating "Ask Sonar" button, visible on every authenticated screen. */
export function SonarFab({ onOpen }: { onOpen: () => void }) {
  return (
    <button className="fab" onClick={onOpen} aria-label="Open Ask Sonar">
      <span className="pulse" />Ask Sonar
    </button>
  );
}
