/**
 * Shell — the authenticated app frame: sidebar + main content.
 * Mirrors the mockup sidebar (Overview / Issues / Files, Progress).
 */

import { useState } from "react";
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
  const [moreOpen, setMoreOpen] = useState(false);
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

      <MobileTabBar
        view={view}
        isAdmin={user.is_admin ?? false}
        repoLabel={repoLabel}
        onNavigate={(v) => { setMoreOpen(false); onNavigate(v); }}
        onOpenSonar={onOpenSonar}
        onRescan={() => { setMoreOpen(false); onRescan(); }}
        onSignOut={onSignOut}
        moreOpen={moreOpen}
        onToggleMore={() => setMoreOpen((o) => !o)}
      />
    </div>
  );
}

/** Five uniform tab glyphs (Lucide-style stroke icons, one family). */
function TabIcon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

/**
 * Floating glass capsule tab bar (mobile). Maps to the five existing app
 * surfaces: Overview, Issues, Fixes navigate; Ask opens the existing Ask
 * Sonar drawer; More holds the plan/billing, admin, re-scan and sign-out
 * actions that already live in the sidebar.
 */
function MobileTabBar({
  view,
  isAdmin,
  repoLabel,
  onNavigate,
  onOpenSonar,
  onRescan,
  onSignOut,
  moreOpen,
  onToggleMore,
}: {
  view: ShellView;
  isAdmin: boolean;
  repoLabel: string | null;
  onNavigate: (view: ShellView) => void;
  onOpenSonar: () => void;
  onRescan: () => void;
  onSignOut: () => void;
  moreOpen: boolean;
  onToggleMore: () => void;
}) {
  const navTabs: { id: string; label: string; d: string; view: ShellView }[] = [
    { id: "overview", label: "Overview", d: "M3 12l9-9 9 9M5 10v10h14V10", view: "overview" },
    { id: "issues", label: "Issues", d: "M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z", view: "issues" },
    { id: "fixes", label: "Fixes", d: "M20 6L9 17l-5-5", view: "fixes" },
  ];
  return (
    <nav className="mobile-tabbar" aria-label="Primary">
      {/* Scroll-edge fade: content melts beneath the floating tab bar. */}
      <div className="scroll-edge-bottom" aria-hidden="true" />
      {navTabs.slice(0, 2).map((t) => (
        <button
          key={t.id}
          className={`tab-item ${view === t.view ? "active" : ""}`}
          onClick={() => onNavigate(t.view)}
          aria-label={t.label}
          aria-current={view === t.view ? "page" : undefined}
        >
          <TabIcon d={t.d} />
          <span className="tab-label">{t.label}</span>
        </button>
      ))}
      {/* Ask is a normal center tab (not raised) — it opens the Ask drawer. */}
      <button className="tab-item" onClick={onOpenSonar} aria-label="Ask Sonar">
        <TabIcon d="M21 12a8 8 0 01-8 8H5l-2 2V12a8 8 0 018-8h2a8 8 0 018 8z" />
        <span className="tab-label">Ask</span>
      </button>
      {navTabs.slice(2, 3).map((t) => (
        <button
          key={t.id}
          className={`tab-item ${view === t.view ? "active" : ""}`}
          onClick={() => onNavigate(t.view)}
          aria-label={t.label}
          aria-current={view === t.view ? "page" : undefined}
        >
          <TabIcon d={t.d} />
          <span className="tab-label">{t.label}</span>
        </button>
      ))}
      <div className="tab-more-wrap">
        {moreOpen && (
          <div className="tab-more-menu" role="menu" aria-label="More">
            <a href="#/pricing" role="menuitem">Plan &amp; billing</a>
            {isAdmin && (
              <button role="menuitem" onClick={() => onNavigate("admin")}>Admin console</button>
            )}
            {repoLabel && (
              <button role="menuitem" onClick={onRescan}>↻ Re-scan repo</button>
            )}
            <hr />
            <button role="menuitem" onClick={onSignOut}>Sign out</button>
          </div>
        )}
        <button
          className="tab-item"
          onClick={onToggleMore}
          aria-label="More"
          aria-expanded={moreOpen}
          aria-haspopup="menu"
        >
          <TabIcon d="M5 12h.01M12 12h.01M19 12h.01" />
          <span className="tab-label">More</span>
        </button>
      </div>
    </nav>
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
