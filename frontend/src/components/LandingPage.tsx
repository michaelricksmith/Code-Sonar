/**
 * LandingPage — the front door. "Descent" theme: monochrome, black hero
 * descending to a white page. Centered hero, sample report dashboard,
 * feature cards, CTA band.
 */

import { useEffect, useState } from "react";

import { GITHUB_LOGIN_URL, GOOGLE_LOGIN_URL } from "../api/auth";
import { GRADE_TONE, GRADE_WORDS, gradeForScore } from "../copy";
import { ScoreDial } from "./ScoreDial";
import { SiteFooter } from "./SiteFooter";

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

function DriftSparkline() {
  return (
    <svg viewBox="0 0 560 150" preserveAspectRatio="none" style={{ width: "100%", height: 120, display: "block" }} aria-hidden="true">
      <defs>
        <linearGradient id="driftFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <g stroke="rgba(255,255,255,0.07)">
        <line x1="0" y1="38" x2="560" y2="38" />
        <line x1="0" y1="75" x2="560" y2="75" />
        <line x1="0" y1="112" x2="560" y2="112" />
      </g>
      <path
        d="M0,120 C50,116 70,104 110,106 C150,108 160,88 210,90 C260,92 270,70 320,72 C370,74 380,52 430,54 C480,56 510,34 560,30 L560,150 L0,150 Z"
        fill="url(#driftFill)"
      />
      <path
        d="M0,120 C50,116 70,104 110,106 C150,108 160,88 210,90 C260,92 270,70 320,72 C370,74 380,52 430,54 C480,56 510,34 560,30"
        fill="none"
        stroke="#ffffff"
        strokeWidth="3"
        style={{ filter: "drop-shadow(0 0 6px rgba(255,255,255,0.7))" }}
      />
      <circle cx="560" cy="30" r="5" fill="#ffffff" />
    </svg>
  );
}

export function LandingPage() {
  const sample = useCountUp(SAMPLE_SCORE);
  const grade = gradeForScore(SAMPLE_SCORE);

  return (
    <div className="descent" id="main-content" tabIndex={-1}>
      <nav className="landing-nav" aria-label="Site">
        <div className="wrap landing-nav-in">
          <a className="brand" href="#/">
            <span className="brand-mark" />
            Code&nbsp;Sonar
          </a>
          <div className="landing-links">
            <a href="#features">How it works</a>
            <a href="#features">What it checks</a>
            <a href="#/pricing">Pricing</a>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <a className="btn btn-ghost btn-sm" href={GITHUB_LOGIN_URL}>Sign in</a>
            <a className="btn btn-primary btn-sm" href={GITHUB_LOGIN_URL}>Get my score</a>
          </div>
        </div>
      </nav>

      <header className="hero-center">
        <span className="announce-pill">
          <i />
          <span><b>New</b>&nbsp;&nbsp;Drift tracking across every scan</span>
        </span>
        <h1>
          What&rsquo;s your code&rsquo;s <span className="accent">credit score?</span>
        </h1>
        <p className="lede">
          Connect your repo and get a 300&ndash;850 health score for your codebase,
          with plain-language findings you can act on. Built for people who ship
          with AI.
        </p>
        <div className="hero-cta">
          <a className="btn btn-primary" href={GITHUB_LOGIN_URL}>Continue with GitHub</a>
          <a className="btn btn-ghost" href={GOOGLE_LOGIN_URL}>Continue with Google</a>
        </div>
        <p className="fine">
          <b>Free for your first repo.</b> No credit card. Your code is never used to train AI.
          <br />
          <span style={{ fontSize: 12.5 }}>
            Switching GitHub accounts?{" "}
            <a
              href="https://github.com/logout"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--muted)", textDecoration: "underline" }}
              title="GitHub remembers your login — sign out there first to switch GitHub accounts"
            >
              sign out of GitHub first
            </a>
            {" "}— Google always asks which account to use.
          </span>
        </p>
      </header>

      <div className="dash-wrap">
        <div className="sample-card" aria-label="Sample Code Sonar report">
          <div className="sample-top">
            <div className="repo-tag">
              <span className="repo-dot" />
              sample / wanderlist-app
            </div>
            <span className={`grade-chip tone-${GRADE_TONE[grade]}`}>Grade {grade} &middot; {GRADE_WORDS[grade]}</span>
          </div>
          <div className="sample-body">
            <div className="sample-dial">
              <div className="eyebrow" style={{ marginBottom: 6 }}>Code health</div>
              <ScoreDial score={sample} width={200} id="landingGrad" />
              <div className="sample-num">{sample}</div>
              <div className="sample-sub">out of 850</div>
            </div>
            <div className="sample-chart">
              <div className="chead"><b>Score drift</b><span>LAST 8 SCANS</span></div>
              <DriftSparkline />
              <div className="verdict-box">
                <b>Fair shape, 3 issues dragging it down.</b> An exposed API key is the
                biggest risk. Fixing it alone could lift this score by about 40 points.
              </div>
            </div>
          </div>
          <div className="sample-stats">
            <div className="sample-stat"><span>Findings</span><b>221</b></div>
            <div className="sample-stat"><span>Debt points</span><b>1,015</b></div>
            <div className="sample-stat"><span>Checks</span><b>8</b></div>
            <div className="sample-stat"><span>Risk files</span><b>14</b></div>
          </div>
        </div>
        <p className="sample-note">Live sample &mdash; sign in to score your own repo.</p>
      </div>

      <div className="trust">
        <div className="wrap">
          <p className="trust-label">THE CREDIT REPORT FOR YOUR CODEBASE</p>
          <div className="trust-in">
            <span><b>8</b>&nbsp;automated checks</span>
            <span><b>300&ndash;850</b>&nbsp;score scale</span>
            <span>Plain-language&nbsp;<b>findings</b></span>
            <span><b>Drift</b>&nbsp;tracking</span>
          </div>
        </div>
      </div>

      <section className="wrap features" id="features">
        <h2>Everything you need to stay sharp</h2>
        <p className="sub">Health monitoring for your codebase, running quietly in the background.</p>
        <div className="cards">
          <div className="card">
            <div className="c-ico">&#9673;</div>
            <h3>One score, zero guesswork</h3>
            <p>
              A 300&ndash;850 health score for the whole repo, like a credit score for your
              code. You know instantly where you stand.
            </p>
          </div>
          <div className="card">
            <div className="c-ico">&#9998;</div>
            <h3>Issues in plain language</h3>
            <p>
              Findings written like a senior dev explaining them, with file, line,
              severity, and fix time on every one.
            </p>
          </div>
          <div className="card">
            <div className="c-ico">&#9672;</div>
            <h3>Watch your score move</h3>
            <p>
              Every scan is compared to the last. See what got better, what got
              worse, and what is quietly rotting.
            </p>
          </div>
        </div>
      </section>

      <section className="wrap">
        <div className="cta-band">
          <h2>Stop guessing. Know your number.</h2>
          <p>
            Join the builders who check their code&rsquo;s health before something breaks.
          </p>
          <div className="signin-row">
            <a className="btn btn-primary" href={GITHUB_LOGIN_URL}>Get my score</a>
            <a className="btn btn-ghost" href={GOOGLE_LOGIN_URL}>Continue with Google</a>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="wrap">
          <SiteFooter />
        </div>
      </footer>
    </div>
  );
}
