import { useState } from "react";
import { GITHUB_LOGIN_URL, GOOGLE_LOGIN_URL } from "../api/auth";

function OAuthButtons() {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
      <a className="btn btn-ghost" href={GITHUB_LOGIN_URL} style={{ flex: 1 }}>
        GitHub
      </a>
      <a className="btn btn-ghost" href={GOOGLE_LOGIN_URL} style={{ flex: 1 }}>
        Google
      </a>
    </div>
  );
}

function Divider() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        margin: "16px 0",
        color: "var(--muted)",
        fontSize: 13,
      }}
    >
      <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
      or
      <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
    </div>
  );
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(data?.detail ?? "Sign in failed.");
      if (data.needs_2fa) {
        sessionStorage.setItem("sonar_pending_2fa", data.pending_token);
        window.location.href = "/2fa/verify";
        return;
      }
      window.location.href = "/app";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
      <h1 className="page-title">Sign in</h1>
      <OAuthButtons />
      <Divider />
      <form onSubmit={submit}>
        <input
          className="input"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          style={{ marginBottom: 8, width: "100%" }}
        />
        <input
          className="input"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
          style={{ marginBottom: 8, width: "100%" }}
        />
        {error && (
          <div className="notice danger" style={{ marginBottom: 8 }}>
            {error}
          </div>
        )}
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy}
          style={{ width: "100%" }}
        >
          {busy ? "Signing in…" : "Sign in with email"}
        </button>
      </form>
      <p className="page-sub" style={{ marginTop: 16, textAlign: "center" }}>
        <a href="#/forgot-password">Forgot password?</a>
        {" · "}
        <a href="#/signup">Create an account</a>
      </p>
    </div>
  );
}

export function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const resp = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password, name }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(data?.detail ?? "Signup failed.");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
        <h1 className="page-title">Check your email</h1>
        <p className="page-sub">
          We sent a verification link to {email}. Click it to activate your
          account, then sign in.
        </p>
        <a className="btn btn-primary" href="#/login">
          Go to sign in
        </a>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
      <h1 className="page-title">Create your account</h1>
      <OAuthButtons />
      <Divider />
      <form onSubmit={submit}>
        <input
          className="input"
          type="text"
          placeholder="Name (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
          style={{ marginBottom: 8, width: "100%" }}
        />
        <input
          className="input"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          style={{ marginBottom: 8, width: "100%" }}
        />
        <input
          className="input"
          type="password"
          placeholder="Password (min 8 characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          autoComplete="new-password"
          style={{ marginBottom: 8, width: "100%" }}
        />
        {error && (
          <div className="notice danger" style={{ marginBottom: 8 }}>
            {error}
          </div>
        )}
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy}
          style={{ width: "100%" }}
        >
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="page-sub" style={{ marginTop: 16, textAlign: "center" }}>
        Already have an account? <a href="#/login">Sign in</a>
      </p>
    </div>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    setBusy(false);
    setDone(true);
  }

  if (done) {
    return (
      <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
        <h1 className="page-title">Check your email</h1>
        <p className="page-sub">
          If an account exists for {email}, you will receive a password reset
          link shortly.
        </p>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
      <h1 className="page-title">Reset password</h1>
      <p className="page-sub">
        Enter your email and we will send you a reset link.
      </p>
      <form onSubmit={submit}>
        <input
          className="input"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          style={{ marginBottom: 8, width: "100%" }}
        />
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy}
          style={{ width: "100%" }}
        >
          {busy ? "Sending…" : "Send reset link"}
        </button>
      </form>
    </div>
  );
}

export function ResetPasswordPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const resp = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(data?.detail ?? "Reset failed.");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
        <h1 className="page-title">Password updated</h1>
        <p className="page-sub">
          Your password has been changed. You have been signed out everywhere.
        </p>
        <a className="btn btn-primary" href="#/login">
          Sign in
        </a>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 400, margin: "60px auto" }}>
      <h1 className="page-title">Choose a new password</h1>
      <form onSubmit={submit}>
        <input
          className="input"
          type="password"
          placeholder="New password (min 8 characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          autoComplete="new-password"
          style={{ marginBottom: 8, width: "100%" }}
        />
        {error && (
          <div className="notice danger" style={{ marginBottom: 8 }}>
            {error}
          </div>
        )}
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || !token}
          style={{ width: "100%" }}
        >
          {busy ? "Updating…" : "Set new password"}
        </button>
      </form>
    </div>
  );
}
