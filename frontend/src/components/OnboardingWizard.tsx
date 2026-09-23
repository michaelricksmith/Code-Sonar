/**
 * OnboardingWizard — first-run flow (§2.4 screen 2, §2.5).
 * Step 1 (sign-in) is done via OAuth before this mounts.
 * Step 2: pick a repo (searchable list + paste-a-URL). Step 3: first scan with
 * animated sonar ring + human steps. Step 4: score reveal + welcome card.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { ScanResponse } from "../api/analyzers";
import { fetchAuthRepos, normalizeRepoInput } from "../api/auth";
import type { RepoOption } from "../api/auth";
import { createScanJob, pollScanJob } from "../api/scanJobs";
import type { ScanJobState } from "../api/scanJobs";
import { GRADE_TONE, GRADE_WORDS, gradeForScore, timeAgo, verdictForScore } from "../copy";
import { ScoreDial } from "./ScoreDial";

type Step = "pick" | "scanning" | "revealing";

interface OnboardingWizardProps {
  userName: string;
  onComplete: (result: ScanResponse, repoLabel: string) => void;
}

const HUMAN_STEPS = [
  "Reading your files…",
  "Running 8 checks…",
  "Tallying your score…",
];

function shortRepoName(fullName: string): string {
  const parts = fullName.split("/");
  return parts[parts.length - 1] ?? fullName;
}

export function OnboardingWizard({ userName, onComplete }: OnboardingWizardProps) {
  const [step, setStep] = useState<Step>("pick");
  const [repos, setRepos] = useState<RepoOption[]>([]);
  const [reposLoading, setReposLoading] = useState(true);
  const [reposError, setReposError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [urlInput, setUrlInput] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [pickedRepo, setPickedRepo] = useState<string | null>(null);
  const [jobState, setJobState] = useState<ScanJobState | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [humanStep, setHumanStep] = useState(0);
  const [revealResult, setRevealResult] = useState<ScanResponse | null>(null);
  const pollRef = useRef<{ cancel: () => void } | null>(null);

  useEffect(() => {
    fetchAuthRepos()
      .then(setRepos)
      .catch((e) => setReposError(e instanceof Error ? e.message : String(e)))
      .finally(() => setReposLoading(false));
  }, []);

  // Rotate the human-readable step captions while the scan runs.
  useEffect(() => {
    if (step !== "scanning") return;
    const timer = setInterval(() => setHumanStep((n) => (n + 1) % HUMAN_STEPS.length), 2600);
    return () => clearInterval(timer);
  }, [step]);

  useEffect(() => () => pollRef.current?.cancel(), []);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return repos;
    return repos.filter((r) => r.full_name.toLowerCase().includes(needle));
  }, [repos, search]);

  async function startScan(repo: string): Promise<void> {
    setPickedRepo(repo);
    setStep("scanning");
    setScanError(null);
    setJobState(null);
    setHumanStep(0);
    try {
      const jobId = await createScanJob(repo);
      const poll = pollScanJob(jobId, (state) => setJobState(state));
      pollRef.current = poll;
      const final = await poll.done;
      if (final.status === "error") {
        setScanError(final.error ?? "The scan failed. Please try again.");
        setStep("pick");
        return;
      }
      if (!final.result) {
        setScanError("The scan finished but returned no result. Please try again.");
        setStep("pick");
        return;
      }
      setStep("revealing");
      setRevealResult(final.result);
      revealThenComplete(final.result, repo);
    } catch (e) {
      setScanError(e instanceof Error ? e.message : String(e));
      setStep("pick");
    }
  }

  function revealThenComplete(result: ScanResponse, repo: string): void {
    // Give the reveal animation room to land before entering the dashboard.
    window.setTimeout(() => onComplete(result, repo), 2600);
  }

  function submitUrl(): void {
    const normalized = normalizeRepoInput(urlInput);
    if (!normalized.includes("/")) {
      setUrlError("That doesn't look like a repo — use owner/name or a full GitHub URL.");
      return;
    }
    setUrlError(null);
    void startScan(normalized);
  }

  const firstName = userName.split(" ")[0] || userName;

  return (
    <div className="wizard">
      <div className="wizard-brand">
        <span className="brand">
          <span className="brand-mark" />
          Code&nbsp;Sonar
        </span>
      </div>

      {step === "pick" && (
        <div className="wizard-card">
          <div className="wizard-dots">
            <i className="on" />
            <i className="on" />
            <i />
          </div>
          <h2>Which project should we score, {firstName}?</h2>
          <p className="wsub">Pick a repo and we&rsquo;ll read it, run 8 checks, and give you one number.</p>

          <div className="repo-search">
            <input
              className="search-input"
              placeholder="Search your repos…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search your repositories"
            />
          </div>

          {reposLoading && (
            <div className="loading-inner" style={{ padding: "28px 0" }}>
              <div className="spinner" />
              Loading your repos…
            </div>
          )}
          {reposError && (
            <div className="notice warning">
              <b>Couldn&rsquo;t load your repos</b>
              {reposError} — you can still paste a repo URL below.
            </div>
          )}
          {!reposLoading && !reposError && (
            <div className="repo-list" role="listbox" aria-label="Your repositories">
              {filtered.length === 0 && <div className="empty-panel">No repos match &ldquo;{search}&rdquo;.</div>}
              {filtered.map((repo) => (
                <button key={String(repo.id)} className="repo-row" onClick={() => void startScan(repo.full_name)}>
                  <span>
                    <span className="rname">{shortRepoName(repo.full_name)}</span>
                    <div className="rmeta">
                      {repo.full_name}
                      {repo.pushed_at ? ` · pushed ${timeAgo(repo.pushed_at)}` : ""}
                    </div>
                  </span>
                  <span className="priv">{repo.private ? "Private" : "Public"}</span>
                  <span className="go">Score →</span>
                </button>
              ))}
            </div>
          )}

          <div className="url-paste">
            <label htmlFor="repo-url">Or paste a repo URL</label>
            <div className="url-row">
              <input
                id="repo-url"
                className="input mono"
                placeholder="owner/repo or https://github.com/owner/repo"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitUrl();
                }}
                spellCheck={false}
              />
              <button className="btn btn-primary" onClick={submitUrl} disabled={!urlInput.trim()}>
                Score it
              </button>
            </div>
            {urlError && <div className="notice warning" style={{ marginTop: 12, marginBottom: 0 }}><b>Check that URL</b>{urlError}</div>}
          </div>

          {scanError && (
            <div className="notice danger" style={{ marginTop: 18, marginBottom: 0 }}>
              <b>Scan didn&rsquo;t start</b>
              {scanError}
            </div>
          )}
        </div>
      )}

      {step === "scanning" && (
        <div className="wizard-card">
          <div className="wizard-dots">
            <i className="on" />
            <i className="on" />
            <i className="on" />
          </div>
          <h2>First scan is running…</h2>
          <div className="sonar-ring-wrap">
            <div className="sonar-ring" aria-hidden="true">
              <div className="ring r1" />
              <div className="ring r2" />
              <div className="ring r3" />
              <div className="core" />
            </div>
            <div className="scan-step">{jobState?.step || HUMAN_STEPS[humanStep]}</div>
            <div className="scan-sub">
              {pickedRepo ? <span className="mono">{pickedRepo}</span> : "Preparing…"} · nothing is changed in your repo
            </div>
            <div className="scan-progress" role="progressbar" aria-label="Scan progress">
              <i style={{ width: `${Math.round((jobState?.progress ?? 0.15) * 100)}%` }} />
            </div>
          </div>
        </div>
      )}

      {step === "revealing" && revealResult && <Reveal result={revealResult} />}
    </div>
  );
}

function Reveal({ result }: { result: ScanResponse }) {
  const [shown, setShown] = useState(0);
  const target = result.score;

  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const duration = 1800;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 4);
      setShown(Math.round(target * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  const grade = gradeForScore(shown);
  const urgentCount = result.findings.filter((f) => f.severity === "critical").length;

  return (
    <div className="wizard-card">
      <div className="wizard-dots">
        <i className="on" />
        <i className="on" />
        <i className="on" />
      </div>
      <h2>Your code has a score</h2>
      <div style={{ display: "flex", justifyContent: "center", marginTop: 18 }}>
        <ScoreDial score={shown} width={220} id="revealGrad" />
      </div>
      <div className="reveal-num">{shown}</div>
      <div style={{ textAlign: "center", marginTop: 10 }}>
        <span className={`grade-chip tone-${GRADE_TONE[grade]}`}>Grade {grade} · {GRADE_WORDS[grade]}</span>
      </div>
      <div className="welcome-card">
        <b>Your code scored — here&rsquo;s what that means.</b>
        <br />
        {verdictForScore(target, urgentCount)}
      </div>
    </div>
  );
}
