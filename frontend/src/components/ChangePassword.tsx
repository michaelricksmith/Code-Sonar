import { useState } from "react";

export function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(false);
    setBusy(true);
    try {
      const resp = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(data?.detail ?? "Could not change password.");
      setDone(true);
      setCurrent("");
      setNext("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="lbl">Password</div>
      <p className="page-sub">
        Change the password on your email sign in. Other sessions will be
        signed out.
      </p>
      <form onSubmit={submit} style={{ marginTop: 8 }}>
        <input
          className="input"
          type="password"
          placeholder="Current password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          style={{ marginBottom: 8, width: "100%", maxWidth: 320 }}
        />
        <input
          className="input"
          type="password"
          placeholder="New password (min 8 characters)"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          minLength={8}
          autoComplete="new-password"
          style={{ marginBottom: 8, width: "100%", maxWidth: 320 }}
        />
        {error && (
          <div className="notice danger" style={{ marginBottom: 8 }}>
            {error}
          </div>
        )}
        {done && (
          <div className="notice success" style={{ marginBottom: 8 }}>
            Password changed.
          </div>
        )}
        <button
          className="btn btn-primary btn-sm"
          type="submit"
          disabled={busy || !current || next.length < 8}
        >
          {busy ? "Updating…" : "Change password"}
        </button>
      </form>
    </section>
  );
}
