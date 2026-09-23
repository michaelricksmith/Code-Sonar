/**
 * Shell — the authenticated app frame: sidebar + main content.
 * Mirrors the mockup sidebar (Overview / Issues / Files, Progress).
 */

import type { ReactNode } from "react";

import type { User } from "../api/auth";

export type ShellView = "overview" | "issues";

interface ShellProps {
  user: User;
  repoLabel: string | null;
  repoSub: string | null;
  view: ShellView;
  issueCount: number | null;
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
  onNavigate,
  onSignOut,
  onOpenSonar,
  children,
}: ShellProps) {
  return (
    <div className="shell">
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
