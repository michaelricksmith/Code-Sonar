/**
 * LandingPage — the front door (§2.4 screen 1, mockup-landing.html).
 * Hero with an animated sample score dial, OAuth sign-in buttons,
 * feature cards, and the privacy footer line.
 */

import { useEffect, useState } from "react";

import { GITHUB_LOGIN_URL, GOOGLE_LOGIN_URL } from "../api/auth";
import { GRADE_TONE, GRADE_WORDS, gradeForScore } from "../copy";
import { ScoreDial } from "./ScoreDial";

const SAMPLE_SCORE = 612;

function useCountUp(target: number, durationMs = 1400): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(target * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);
  return value;
}

function OAuthButtons({ dark = false }: { dark?: boolean }) {
  return (
    <div className="signin-row">
      <a className={dark ? "btn btn-dark" : "btn btn-dark"} href={GITHUB_LOGIN_URL}>
        <span className="oauth-icon">⌥</span>Sign in with GitHub
      </a>
      <a
        className="btn btn-ghost"
        style={dark ? { background: "transparent", color: "#fff", borderColor: "#3A4450" } : undefined}
        href={GOOGLE_LOGIN_URL}
      >
        <span className="oauth-icon" style={{ color: dark ? "#fff" : "#4285F4" }}>G</span>Sign in with Google
      </a>
    </div>
  );
}

export function LandingPage() {
  const sample = useCountUp(SAMPLE_SCORE);
  const grade = gradeForScore(SAMPLE_SCORE);

  return (
    <div>
      <nav className="landing-nav">
        <div className="wrap landing-nav-in">
          <a className="brand" href="#/">
            <span className="brand-mark" />
            Code&nbsp;Sonar
          </a>
          <div className="landing-links">
            <a href="#features">How it works</a>
            <a href="#features">What it checks</a>
            <a href="#features">Pricing</a>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <a className="btn btn-ghost btn-sm" href={GITHUB_LOGIN_URL}>Sign in</a>
            <a className="btn btn-primary btn-sm" href={GITHUB_LOGIN_URL}>Get my score</a>
          </div>
        </div>
      </nav>

      <header className="wrap hero">
        <div>
          <span className="kicker">The credit report for your codebase</span>
          <h1>
            What&rsquo;s your code&rsquo;s <span className="accent">credit score?</span>
          </h1>
          <p className="lede">
            Connect your repo and get a single 300–850 score for your code&rsquo;s health —
            with plain-language reasons and one-click fixes. Built for people who ship
            with AI, not for people who read stack traces for fun.
          </p>
          <OAuthButtons />
          <p className="fine">
            <b>Free for your first repo.</b> No credit card. Your code is never used to train AI.
          </p>
        </div>

        <div className="sample-card" aria-label="Sample Code Sonar report">
          <div className="sample-top">
            <div className="repo-tag">
              <span className="repo-dot" />
              sample / wanderlist-app
            </div>
            <span className={`grade-chip tone-${GRADE_TONE[grade]}`}>Grade {grade} · {GRADE_WORDS[grade]}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "center", margin: "18px 0 8px" }}>
            <ScoreDial score={sample} width={240} id="landingGrad" />
          </div>
          <div className="sample-num">{sample}</div>
          <div className="sample-sub">out of 850 · sample report</div>
          <div className="verdict-box">
            <b>Fair shape, 3 issues dragging it down.</b> An exposed API key is the
            biggest risk — fixing it alone could lift this score by ~40 points.
          </div>
          <div className="sample-cta">
            <a className="btn btn-primary" href={GITHUB_LOGIN_URL}>See what&rsquo;s wrong</a>
            <a className="btn btn-ghost" href={GITHUB_LOGIN_URL}>Fix the top issue</a>
          </div>
          <div className="sample-note">Live sample — sign in to score your own repo.</div>
        </div>
      </header>

      <div className="trust">
        <div className="wrap trust-in">
          <span><span className="t-ico">✓</span>Deterministic scoring — same code, same score, every time</span>
          <span><span className="t-ico">✓</span>Secrets are never shown or stored in plain text</span>
          <span><span className="t-ico">✓</span>8 automated checks on every scan</span>
        </div>
      </div>

      <section className="wrap features" id="features">
        <h2>Your code, explained like a friend would</h2>
        <p className="sub">No jargon. No 40-tab docs. Just: here&rsquo;s your score, here&rsquo;s why, here&rsquo;s the fix.</p>
        <div className="cards">
          <div className="card">
            <div className="c-ico c1">◉</div>
            <h3>One score, zero guesswork</h3>
            <p>
              Every repo gets a 300–850 health score, like a credit score for your code.
              You know instantly whether things are healthy, shaky, or on fire — and
              exactly which files moved the number.
            </p>
          </div>
          <div className="card">
            <div className="c-ico c2">✎</div>
            <h3>Issues in plain language</h3>
            <p>
              &ldquo;Tangled logic in checkout.js&rdquo; — not &ldquo;cyclomatic complexity ≥ 10&rdquo;.
              Every issue comes with a plain-language explanation of what&rsquo;s wrong and
              why it matters to your app.
            </p>
          </div>
          <div className="card">
            <div className="c-ico c3">⚡</div>
            <h3>Guided fixes, one click</h3>
            <p>
              Sonar writes the fix, runs your tests, and re-scores. You approve each
              step. Watch your score climb as issues get resolved — 612 → 638 → 705.
            </p>
          </div>
        </div>
      </section>

      <section className="wrap how">
        <h2>From sign-in to first score in under two minutes</h2>
        <div className="steps">
          <div className="step-blurb">
            <div className="n">1</div>
            <h3>Sign in with GitHub or Google</h3>
            <p>Two clicks. No passwords, no config files, no terminal.</p>
          </div>
          <div className="step-blurb">
            <div className="n">2</div>
            <h3>Pick a repo</h3>
            <p>Choose from your repos. Sonar reads the code — nothing is installed in your project.</p>
          </div>
          <div className="step-blurb">
            <div className="n">3</div>
            <h3>Get your score</h3>
            <p>Watch the dial land, then start with the top issue. Most first fixes take under 10 minutes.</p>
          </div>
        </div>
      </section>

      <section className="wrap">
        <div className="cta-band">
          <h2>Stop guessing. Know your number.</h2>
          <p>
            Join the builders who check their code&rsquo;s health the way they check their
            credit — regularly, and before something breaks.
          </p>
          <OAuthButtons dark />
        </div>
      </section>

      <footer className="landing-footer">
        <div className="wrap foot-in">
          <div>
            <span className="brand" style={{ fontSize: 15 }}>
              <span className="brand-mark" style={{ width: 26, height: 26 }} />
              Code&nbsp;Sonar
            </span>
            <div style={{ marginTop: 8 }}>
              © 2026 Michael Smith. We read your code to score it. We never train on it.
            </div>
          </div>
          <div>
            <a href="#/">Privacy</a>
            <a href="#/">Security</a>
            <a href="#/">Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
