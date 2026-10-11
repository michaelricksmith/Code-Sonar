import { useState } from "react";

export function TwoFAVerify() {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // Password logins stash the pending token in sessionStorage
      // (no cookie yet); OAuth logins carry it as a cookie.
      const pendingToken = sessionStorage.getItem("sonar_pending_2fa");
      const resp = await fetch("/api/2fa/verify-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ code, pending_token: pendingToken }),
      });
      if (resp.status === 204) {
        sessionStorage.removeItem("sonar_pending_2fa");
        window.location.href = "/app";
        return;
      }
      const data = await resp.json().catch(() => null);
      setError(data?.detail ?? "Verification failed.");
    } catch {
      setError("Network error. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 420, margin: "60px auto" }}>
      <h1 className="page-title">Two factor verification</h1>
      <p className="page-sub">
        Enter the 6 digit code from your authenticator app. You can also use
        one of your backup codes.
      </p>
      <form onSubmit={submit}>
        <input
          className="input"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
          autoFocus
          style={{ fontSize: 24, letterSpacing: 8, textAlign: "center" }}
        />
        {error && (
          <div className="notice danger" style={{ marginTop: 12 }}>
            {error}
          </div>
        )}
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || code.length < 6}
          style={{ marginTop: 16, width: "100%" }}
        >
          {busy ? "Verifying…" : "Verify"}
        </button>
      </form>
    </div>
  );
}
