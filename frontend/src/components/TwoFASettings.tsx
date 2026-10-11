import { useEffect, useState } from "react";

interface Status {
  enabled: boolean;
  enrolled_at: string | null;
  backup_codes_remaining: number;
}

export function TwoFASettings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [qrSvg, setQrSvg] = useState<string | null>(null);
  const [manualCode, setManualCode] = useState<string | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const resp = await fetch("/api/2fa/status", { credentials: "include" });
    if (resp.ok) setStatus(await resp.json());
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function enroll() {
    setError(null);
    setBusy(true);
    try {
      const resp = await fetch("/api/2fa/enroll", {
        method: "POST",
        credentials: "include",
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data?.detail ?? "Enrollment failed.");
      setQrSvg(data.qr_svg);
      setManualCode(data.manual_entry_code);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Enrollment failed.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setError(null);
    setBusy(true);
    try {
      const resp = await fetch("/api/2fa/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ code: confirmCode }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data?.detail ?? "Invalid code.");
      setBackupCodes(data.backup_codes);
      setQrSvg(null);
      setManualCode(null);
      setConfirmCode("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid code.");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    const code = window.prompt("Enter a current authenticator code to disable 2FA:");
    if (!code) return;
    setError(null);
    const resp = await fetch("/api/2fa/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ code }),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
      setError(data?.detail ?? "Could not disable 2FA.");
      return;
    }
    setBackupCodes(null);
    await refresh();
  }

  if (!status) return null;

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="lbl">Two factor authentication</div>
      {status.enabled ? (
        <div style={{ marginTop: 8 }}>
          <p style={{ color: "var(--good)", fontWeight: 600 }}>
            ✓ Enabled{status.enrolled_at ? ` since ${new Date(status.enrolled_at).toLocaleDateString()}` : ""}
          </p>
          <p className="page-sub">
            {status.backup_codes_remaining} backup codes remaining.
          </p>
          <button className="btn btn-ghost btn-sm" onClick={disable}>
            Disable 2FA
          </button>
        </div>
      ) : backupCodes ? (
        <div style={{ marginTop: 8 }}>
          <p style={{ color: "var(--good)", fontWeight: 600 }}>✓ 2FA is now enabled.</p>
          <p className="page-sub">
            Save these backup codes somewhere safe. Each works once if you
            lose your authenticator.
          </p>
          <pre
            style={{
              background: "var(--bg-soft)",
              padding: 12,
              borderRadius: 8,
              fontSize: 15,
              letterSpacing: 1,
            }}
          >
            {backupCodes.join("\n")}
          </pre>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setBackupCodes(null)}
          >
            I saved my backup codes
          </button>
        </div>
      ) : qrSvg ? (
        <div style={{ marginTop: 8 }}>
          <p className="page-sub">
            Scan this QR code with your authenticator app, then enter the
            6 digit code to confirm.
          </p>
          <div dangerouslySetInnerHTML={{ __html: qrSvg }} style={{ maxWidth: 220 }} />
          {manualCode && (
            <p className="page-sub" style={{ marginTop: 8 }}>
              Or enter manually: <code>{manualCode}</code>
            </p>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              className="input"
              inputMode="numeric"
              placeholder="123456"
              value={confirmCode}
              onChange={(e) => setConfirmCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              style={{ maxWidth: 160 }}
            />
            <button
              className="btn btn-primary btn-sm"
              onClick={confirm}
              disabled={busy || confirmCode.length !== 6}
            >
              Confirm
            </button>
          </div>
        </div>
      ) : (
        <div style={{ marginTop: 8 }}>
          <p className="page-sub">
            Add a second factor to your sign in. You will enter a code from
            your authenticator app after signing in with GitHub or Google.
          </p>
          <button className="btn btn-primary btn-sm" onClick={enroll} disabled={busy}>
            {busy ? "Setting up…" : "Enable 2FA"}
          </button>
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
