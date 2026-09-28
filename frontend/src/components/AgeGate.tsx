/**
 * AgeGate — neutral age check shown to signed-in users who haven't
 * completed it. No pre-selected year, no suggestive wording. Under-13
 * sign-ups are scrubbed server-side and signed out.
 */

import { useState } from "react";

import { logout } from "../api/auth";
import {
  blockUnderageAccount,
  isUnderageBlockedError,
  setMarketingConsent,
  submitAgeGate,
} from "../api/compliance";

const OLDEST_YEAR_SPAN = 120;

function birthYears(): number[] {
  const current = new Date().getFullYear();
  const years: number[] = [];
  for (let y = current; y >= current - OLDEST_YEAR_SPAN; y--) years.push(y);
  return years;
}

interface AgeGateProps {
  /** Called once the gate is completed (adult bracket verified). */
  onComplete: () => void;
}

export function AgeGate({ onComplete }: AgeGateProps) {
  const [birthYear, setBirthYear] = useState("");
  const [marketing, setMarketing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removed, setRemoved] = useState(false);

  async function handleContinue(): Promise<void> {
    if (!birthYear || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitAgeGate(Number(birthYear));
      if (marketing) {
        try {
          await setMarketingConsent(true);
        } catch {
          // Best-effort: a failed marketing opt-in must not block the gate.
        }
      }
      onComplete();
    } catch (e) {
      if (isUnderageBlockedError(e)) {
        try {
          await blockUnderageAccount();
        } catch {
          // Best-effort: still sign out locally so the account can't proceed.
        }
        try {
          await logout();
        } catch {
          // Even if the server call fails, the session is dropped below.
        }
        setRemoved(true);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (removed) {
    return (
      <div className="page age-gate">
        <div className="card age-gate-card">
          <h1 className="page-title" style={{ fontSize: 26 }}>Thanks for stopping by</h1>
          <p className="page-sub">
            Code Sonar is for people 13 and older. Your sign-up has been removed.
          </p>
          <button className="btn btn-ghost" onClick={() => window.location.reload()}>
            Back to sign-in
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page age-gate">
      <div className="card age-gate-card">
        <span className="kicker">One quick check</span>
        <h1 className="page-title" style={{ fontSize: 26 }}>What year were you born?</h1>
        <p className="page-sub">
          We ask everyone once, so we can keep Code Sonar safe for younger builders.
        </p>

        <label className="age-gate-label" htmlFor="age-gate-year">
          Birth year
        </label>
        <select
          id="age-gate-year"
          className="input"
          value={birthYear}
          onChange={(e) => setBirthYear(e.target.value)}
          disabled={submitting}
        >
          <option value="" disabled>
            Select your birth year
          </option>
          {birthYears().map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>

        <label className="consent-check age-gate-marketing">
          <input
            type="checkbox"
            checked={marketing}
            onChange={(e) => setMarketing(e.target.checked)}
            disabled={submitting}
          />
          <span>Email me product updates and tips (optional).</span>
        </label>

        {error && (
          <div className="notice danger" role="alert" style={{ marginTop: 14 }}>
            <b>Couldn&rsquo;t verify</b>
            {error}
          </div>
        )}

        <button
          className="btn btn-primary"
          style={{ width: "100%", marginTop: 18 }}
          onClick={() => void handleContinue()}
          disabled={!birthYear || submitting}
        >
          {submitting ? "Checking…" : "Continue"}
        </button>
      </div>
    </div>
  );
}
