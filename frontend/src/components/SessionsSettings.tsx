import { useEffect, useState } from "react";

interface Session {
  session_id: string;
  created_at: string;
  last_seen_at: string | null;
  device_info: string | null;
  ip_address: string | null;
  is_current: boolean;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function SessionsSettings() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const resp = await fetch("/api/sessions", { credentials: "include" });
    if (resp.ok) {
      const data = await resp.json();
      setSessions(data.sessions);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function revoke(sessionId: string) {
    setError(null);
    const resp = await fetch(`/api/sessions/${sessionId}/revoke`, {
      method: "POST",
      credentials: "include",
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => null);
      setError(data?.detail ?? "Could not revoke session.");
      return;
    }
    void refresh();
  }

  async function revokeOthers() {
    if (!window.confirm("Sign out all other sessions?")) return;
    setError(null);
    const resp = await fetch("/api/sessions/revoke-others", {
      method: "POST",
      credentials: "include",
    });
    if (!resp.ok) {
      setError("Could not sign out other sessions.");
      return;
    }
    void refresh();
  }

  if (!sessions) return null;

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="lbl">Active sessions</div>
      <p className="page-sub">
        Devices signed in to your account. Revoke any you do not recognize.
      </p>
      {sessions.length === 0 ? (
        <p className="page-sub">No active sessions.</p>
      ) : (
        <div style={{ marginTop: 8 }}>
          {sessions.map((s) => (
            <div
              key={s.session_id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "8px 0",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <div>
                <div style={{ fontWeight: 600 }}>
                  {s.device_info || "Unknown device"}
                  {s.is_current && (
                    <span
                      style={{
                        marginLeft: 8,
                        fontSize: 12,
                        color: "var(--good)",
                        fontWeight: 600,
                      }}
                    >
                      This device
                    </span>
                  )}
                </div>
                <div className="lbl">
                  {s.ip_address ?? "unknown IP"} · last seen {timeAgo(s.last_seen_at)}
                </div>
              </div>
              {!s.is_current && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => void revoke(s.session_id)}
                >
                  Revoke
                </button>
              )}
            </div>
          ))}
          {sessions.length > 1 && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => void revokeOthers()}
              style={{ marginTop: 12 }}
            >
              Sign out all other sessions
            </button>
          )}
        </div>
      )}
      {error && (
        <div className="notice danger" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}
    </section>
  );
}
