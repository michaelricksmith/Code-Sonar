/**
 * Shell — the authenticated app frame: sidebar + main content.
 * Mirrors the mockup sidebar (Overview / Issues / Files, Progress).
 */

import type { ReactNode } from "react";

import type { User } from "../api/auth";

export type ShellView = "overview" | "issues" | "fixes";

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
  children,
}: ShellProps) {
  return (
    <div className="shell">
      <div className="mobile-topbar">
        <a className="brand" href="#/app">
          <span className="brand-mark" />
          Code&nbsp;Sonar
        </a>
        <button className="signout" onClick={onSignOut} title="Sign out">Sign out</button>
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
                  <div className="side-detail-row">
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
        </div>

        <div className="side-foot">
          <div className="user-chip" style={{ padding: "0 0 10px" }}>
            {user.avatar_url ? <img src={user.avatar_url} alt="" /> : <span className="brand-mark" style={{ width: 32, height: 32 }} />}
            <span className="who">
              <b>{user.name}</b>
              <span>{user.email}</span>
            </span>
            <button className="signout" onClick={onSignOut} title="Sign out">Sign out</button>
          </div>
          <div><span className="dot" />Sonar is watching · {repoLabel ? "repo connected" : "no repo yet"}</div>
        </div>
      </aside>

      <section className="main">{children}</section>
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
