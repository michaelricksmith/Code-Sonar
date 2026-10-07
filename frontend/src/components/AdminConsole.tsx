/**
 * AdminConsole — team management for admins.
 *
 * Lists users with plan, usage, and privilege flags. Admins can grant or
 * revoke the staff flag (unlimited testing quota) and the admin flag.
 * Rendered only for admin users (route-guarded in App).
 */

import { useCallback, useEffect, useState } from "react";

import type { AdminUser } from "../api/admin";
import {
  deleteUser,
  fetchAdminUsers,
  resetUserUsage,
  setUserAdmin,
  setUserPlan,
  setUserStaff,
} from "../api/admin";

function FlagBadge({ label, on }: { label: string; on: boolean }) {
  return (
    <span
      className="plan-badge"
      style={
        on
          ? { background: "var(--teal)", color: "#fff", borderColor: "transparent" }
          : { opacity: 0.45 }
      }
      title={on ? `${label} granted` : `${label} not granted`}
    >
      {label}
    </span>
  );
}

export function AdminConsole({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await fetchAdminUsers();
      setUsers(data.users);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = useCallback(
    async (target: AdminUser, kind: "staff" | "admin") => {
      const next = kind === "staff" ? !target.is_staff : !target.is_admin;
      if (kind === "admin") {
        const action = next ? "Grant admin to" : "Remove admin from";
        const note = next
          ? "Admins can manage the team and change flags."
          : "They will lose access to this console.";
        if (!window.confirm(`${action} ${target.name || target.email}?\n${note}`)) return;
      }
      const key = `${target.id}:${kind}`;
      setBusy(key);
      setError(null);
      try {
        const updated =
          kind === "staff" ? await setUserStaff(target.id, next) : await setUserAdmin(target.id, next);
        setUsers((prev) => prev?.map((u) => (u.id === target.id ? updated : u)) ?? null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
      }
    },
    []
  );

  const changePlan = useCallback(async (target: AdminUser, plan: string) => {
    if (plan === target.plan) return;
    if (
      !window.confirm(
        `Set ${target.name || target.email}'s plan to ${plan}?\nNo Stripe charge — this is a direct admin grant.`
      )
    )
      return;
    const key = `${target.id}:plan`;
    setBusy(key);
    setError(null);
    try {
      const updated = await setUserPlan(target.id, plan);
      setUsers((prev) => prev?.map((u) => (u.id === target.id ? updated : u)) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  const resetUsage = useCallback(async (target: AdminUser) => {
    if (
      !window.confirm(
        `Reset usage counters for ${target.name || target.email}?\nTheir scans and Ask Sonar quota go back to zero for this period.`
      )
    )
      return;
    const key = `${target.id}:usage`;
    setBusy(key);
    setError(null);
    try {
      const usage = await resetUserUsage(target.id);
      setUsers((prev) => prev?.map((u) => (u.id === target.id ? { ...u, usage } : u)) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  const removeUser = useCallback(
    async (target: AdminUser) => {
      if (target.id === currentUserId) return;
      if (
        !window.confirm(
          `Permanently delete ${target.name || target.email}?\nTheir account and quota counters are removed. This cannot be undone.`
        )
      )
        return;
      const key = `${target.id}:delete`;
      setBusy(key);
      setError(null);
      try {
        await deleteUser(target.id);
        setUsers((prev) => prev?.filter((u) => u.id !== target.id) ?? null);
        setTotal((t) => Math.max(0, t - 1));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
      }
    },
    [currentUserId]
  );

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "28px 20px 60px" }}>
      <h1 style={{ fontSize: 26, letterSpacing: "-0.01em", marginBottom: 6 }}>Admin console</h1>
      <p style={{ color: "var(--muted)", marginBottom: 20 }}>
        {total} user{total === 1 ? "" : "s"}. Staff get unlimited scans and Ask Sonar for testing.
        Admins can also grant plans, reset quota, and delete accounts.
      </p>

      {error && (
        <div
          role="alert"
          style={{
            background: "rgba(251,113,133,0.08)",
            border: "1px solid rgba(251,113,133,0.35)",
            color: "#fda4af",
            borderRadius: 12,
            padding: "12px 16px",
            marginBottom: 16,
          }}
        >
          {error}{" "}
          <button className="btn btn-ghost btn-sm" onClick={load} style={{ marginLeft: 8 }}>
            Retry
          </button>
        </div>
      )}

      {users === null && !error && <p style={{ color: "var(--muted)" }}>Loading users…</p>}

      {users !== null && (
        <div style={{ overflowX: "auto", border: "1px solid var(--line)", borderRadius: 16, background: "var(--surface)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid var(--line)" }}>
                {["User", "Plan", "Usage", "Flags", "Actions"].map((h) => (
                  <th key={h} style={{ padding: "12px 16px", color: "var(--muted)", fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid var(--line)" }}>
                  <td style={{ padding: "12px 16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      {u.avatar_url ? (
                        <img src={u.avatar_url} alt="" width={32} height={32} style={{ borderRadius: "50%" }} />
                      ) : (
                        <span className="brand-mark" style={{ width: 32, height: 32 }} />
                      )}
                      <div>
                        <div style={{ fontWeight: 600 }}>
                          {u.name || "Unnamed"}
                          {u.id === currentUserId && (
                            <span style={{ color: "var(--muted)", fontWeight: 400 }}> (you)</span>
                          )}
                        </div>
                        <div style={{ color: "var(--muted)", fontSize: 12.5 }}>{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    {u.is_staff ? (
                      <span
                        className="plan-badge"
                        style={{ background: "var(--teal)", color: "#000", borderColor: "transparent" }}
                        title="Internal team: unlimited testing quota, no billing plan"
                      >
                        Staff
                      </span>
                    ) : (
                      <select
                        value={u.plan}
                        disabled={busy !== null}
                        onChange={(e) => changePlan(u, e.target.value)}
                        title="Set billing plan (admin grant, no Stripe charge)"
                        style={{
                          background: "var(--surface)",
                          color: "var(--ink)",
                          border: "1px solid var(--line)",
                          borderRadius: 8,
                          padding: "4px 8px",
                          fontSize: 13,
                        }}
                      >
                        <option value="free">free</option>
                        <option value="hobby">hobby</option>
                        <option value="plus">plus</option>
                      </select>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", color: "var(--muted)", whiteSpace: "nowrap" }}>
                    ◈ {u.usage.scans_used} scans · ✦ {u.usage.ask_sonar_used} asks
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ display: "inline-flex", gap: 6 }}>
                      <FlagBadge label="staff" on={u.is_staff} />
                      <FlagBadge label="admin" on={u.is_admin} />
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={busy !== null}
                      onClick={() => toggle(u, "staff")}
                      title={u.is_staff ? "Remove unlimited testing quota" : "Grant unlimited testing quota"}
                    >
                      {busy === `${u.id}:staff` ? "…" : u.is_staff ? "Remove staff" : "Make staff"}
                    </button>{" "}
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={busy !== null || u.id === currentUserId}
                      onClick={() => toggle(u, "admin")}
                      title={u.id === currentUserId ? "You cannot change your own admin flag" : u.is_admin ? "Remove admin access" : "Grant admin access"}
                    >
                      {busy === `${u.id}:admin` ? "…" : u.is_admin ? "Remove admin" : "Make admin"}
                    </button>{" "}
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={busy !== null}
                      onClick={() => resetUsage(u)}
                      title="Zero this user's scans and Ask Sonar counters for the current period"
                    >
                      {busy === `${u.id}:usage` ? "…" : "Reset quota"}
                    </button>{" "}
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={busy !== null || u.id === currentUserId}
                      onClick={() => removeUser(u)}
                      title={
                        u.id === currentUserId
                          ? "You cannot delete your own account"
                          : "Permanently delete this user"
                      }
                      style={{ color: "#fda4af" }}
                    >
                      {busy === `${u.id}:delete` ? "…" : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ padding: "24px 16px", color: "var(--muted)", textAlign: "center" }}>
                    No users yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
