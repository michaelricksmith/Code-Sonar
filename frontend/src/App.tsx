/**
 * Code Sonar — light "credit report" experience for vibe coders.
 *
 * Routes (hash):
 *   #/                 landing (unauthenticated front door)
 *   #/app              onboarding wizard (new user) or dashboard (has scan)
 *   #/app/issues       full ranked issue list
 *   #/app/issues/:id   issue detail + guided fix
 *
 * The backend OAuth callbacks 302 back to /app (pathname) — the router
 * treats a /app pathname as the app root too.
 *
 * Engine APIs are reused unchanged: scan jobs, drift, ask-sonar (grounded
 * answers + remediation with signed single-use approvals).
 */

import { useCallback, useEffect, useState } from "react";

import type { DriftResult, Finding, ScanResponse } from "./api/analyzers";
import { fetchDrift, fetchHistoryCount } from "./api/analyzers";
import { fetchMe, logout } from "./api/auth";
import type { User } from "./api/auth";
import { fetchAiProviders } from "./api/askSonar";
import type { AiProvider } from "./api/askSonar";
import { createScanJob, pollScanJob } from "./api/scanJobs";
import { fetchFixLog } from "./api/outcomes";
import { fetchPromptStatus } from "./api/prompts";
import { AskSonarDrawer } from "./components/AskSonarDrawer";
import { Dashboard } from "./components/Dashboard";
import { FixesView } from "./components/FixesView";
import { IssueDetail } from "./components/IssueDetail";
import { IssuesView } from "./components/IssuesView";
import { LandingPage } from "./components/LandingPage";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { Shell, SonarFab } from "./components/Shell";
import type { ShellView } from "./components/Shell";
import { timeAgo } from "./copy";

type Route =
  | { name: "landing" }
  | { name: "app" }
  | { name: "issues" }
  | { name: "issue"; id: string }
  | { name: "fixes" };

const LAST_SCAN_KEY = "code-sonar:last-scan";

function parseRoute(): Route {
  const hash = window.location.hash.replace(/^#/, "");
  if (window.location.pathname.startsWith("/app") && (hash === "" || hash === "/")) {
    return { name: "app" };
  }
  if (hash === "" || hash === "/") return { name: "landing" };
  if (hash === "/app") return { name: "app" };
  if (hash === "/app/issues") return { name: "issues" };
  if (hash === "/app/fixes") return { name: "fixes" };
  const match = hash.match(/^\/app\/issues\/(.+)$/);
  if (match) return { name: "issue", id: decodeURIComponent(match[1]) };
  return { name: "landing" };
}

function navigate(to: string): void {
  if (window.location.hash === `#${to}`) return;
  window.location.hash = `#${to}`;
}

function loadSavedScan(): { result: ScanResponse; repoLabel: string } | null {
  try {
    const raw = window.localStorage.getItem(LAST_SCAN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { result: ScanResponse; repoLabel: string };
    if (!parsed?.result || typeof parsed.result.score !== "number") return null;
    return parsed;
  } catch {
    return null;
  }
}

export default function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>(() => parseRoute());
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [repoLabel, setRepoLabel] = useState<string | null>(null);
  const [drift, setDrift] = useState<DriftResult | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [scanNotice, setScanNotice] = useState<string | null>(null);
  const [sonarOpen, setSonarOpen] = useState(false);
  const [sonarQuestion, setSonarQuestion] = useState<string | null>(null);
  const [fixCount, setFixCount] = useState<number | null>(null);
  const [promptActivity, setPromptActivity] = useState<{
    inProgress: number;
    resolved: number;
    stillOpen: number;
  } | null>(null);
  /** Bumped whenever a fix prompt is copied, so the sidebar activity refreshes. */
  const [promptTick, setPromptTick] = useState(0);
  const [providers, setProviders] = useState<AiProvider[] | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [aiProvider, setAiProvider] = useState("");
  const [aiKey, setAiKey] = useState("");

  // Auth check on boot.
  useEffect(() => {
    fetchMe()
      .then((me) => {
        setUser(me);
        if (me) {
          const saved = loadSavedScan();
          if (saved) {
            // Self-heal a stale cache: if the server has no scan history
            // (e.g. after a server-side data reset), drop the cached scan
            // instead of rendering phantom results. If the check itself
            // fails, keep the cache (offline-friendly).
            fetchHistoryCount()
              .then((count) => {
                if (count > 0) {
                  setResult(saved.result);
                  setRepoLabel(saved.repoLabel);
                } else {
                  try {
                    window.localStorage.removeItem(LAST_SCAN_KEY);
                  } catch {
                    // best-effort
                  }
                }
              })
              .catch(() => {
                setResult(saved.result);
                setRepoLabel(saved.repoLabel);
              });
          }
        }
      })
      .catch((e) => setAuthError(e instanceof Error ? e.message : String(e)))
      .finally(() => setAuthChecked(true));
  }, []);

  // AI providers (honest status, BYOK fallback).
  useEffect(() => {
    if (!user) return;
    fetchAiProviders()
      .then(setProviders)
      .catch((e) => setProvidersError(e instanceof Error ? e.message : String(e)));
  }, [user]);

  // Fix-log badge + prompt-first fix activity for the sidebar.
  useEffect(() => {
    if (!user || !repoLabel) {
      setFixCount(null);
      setPromptActivity(null);
      return;
    }
    let cancelled = false;
    fetchFixLog(repoLabel, 1)
      .then((data) => {
        if (!cancelled) setFixCount(data.count);
      })
      .catch(() => {
        if (!cancelled) setFixCount(null);
      });
    // Prompt-first activity: prompts copied, reconciled against the latest
    // scan. Refreshed on navigation, on new scans, and when a prompt is copied.
    fetchPromptStatus(repoLabel)
      .then((items) => {
        if (cancelled) return;
        setPromptActivity({
          inProgress: items.filter((i) => i.status === "in_progress").length,
          resolved: items.filter((i) => i.status === "resolved").length,
          stillOpen: items.filter((i) => i.status === "still_open").length,
        });
      })
      .catch(() => {
        if (!cancelled) setPromptActivity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [user, repoLabel, route.name, result?.scan_id, promptTick]);

  // Hash routing.
  useEffect(() => {
    const onHash = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Route guards.
  useEffect(() => {
    if (!authChecked) return;
    if (!user && route.name !== "landing") navigate("/");
    if (user && route.name === "landing") navigate("/app");
  }, [authChecked, user, route.name]);

  const persistScan = useCallback((next: ScanResponse, label: string) => {
    setResult(next);
    setRepoLabel(label);
    try {
      window.localStorage.setItem(LAST_SCAN_KEY, JSON.stringify({ result: next, repoLabel: label }));
    } catch {
      // Storage is best-effort; the in-memory state is authoritative.
    }
  }, []);

  const refreshDrift = useCallback(async (label: string) => {
    try {
      setDrift(await fetchDrift(label));
    } catch {
      setDrift(null);
    }
  }, []);

  const handleOnboardingComplete = useCallback(
    (scanResult: ScanResponse, label: string) => {
      persistScan(scanResult, label);
      setDrift(null);
      void refreshDrift(label);
      navigate("/app");
    },
    [persistScan, refreshDrift],
  );

  const handleRescan = useCallback(async () => {
    if (!repoLabel || rescanning) return;
    setRescanning(true);
    setScanNotice(null);
    try {
      const jobId = await createScanJob(repoLabel);
      const { done } = pollScanJob(jobId, () => undefined);
      const final = await done;
      if (final.status === "error") throw new Error(final.error ?? "Re-scan failed.");
      if (!final.result) throw new Error("Re-scan finished without a result.");
      persistScan(final.result, repoLabel);
      setScanNotice(`Re-scanned just now — score ${final.result.score}.`);
      void refreshDrift(repoLabel);
    } catch (e) {
      setScanNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setRescanning(false);
    }
  }, [repoLabel, rescanning, persistScan, refreshDrift]);

  const handleAddRepo = useCallback(() => {
    setResult(null);
    setRepoLabel(null);
    setDrift(null);
    try {
      window.localStorage.removeItem(LAST_SCAN_KEY);
    } catch {
      // best-effort
    }
    navigate("/app");
  }, []);

  const handleSignOut = useCallback(async () => {
    try {
      await logout();
    } catch {
      // Even if the server call fails, drop the client session.
    }
    setUser(null);
    navigate("/");
  }, []);

  const openSonar = useCallback((question?: string) => {
    if (question) setSonarQuestion(question);
    setSonarOpen(true);
  }, []);

  const openIssue = useCallback((finding: Finding) => {
    navigate(`/app/issues/${encodeURIComponent(finding.id)}`);
  }, []);

  const aiReady = providers?.some((p) => p.configured) ?? false;

  if (!authChecked) {
    return (
      <div className="loading-screen">
        <div className="loading-inner">
          <div className="spinner" />
          Waking up Sonar…
        </div>
      </div>
    );
  }

  if (authError) {
    return (
      <div className="loading-screen">
        <div className="loading-inner" style={{ maxWidth: 420 }}>
          <p style={{ marginBottom: 14 }}>Sonar couldn&rsquo;t reach the server.</p>
          <p style={{ fontSize: 12.5, marginBottom: 18 }}>{authError}</p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>Try again</button>
        </div>
      </div>
    );
  }

  if (!user) return <LandingPage />;

  const shellView: ShellView =
    route.name === "issues" || route.name === "issue" ? "issues" : route.name === "fixes" ? "fixes" : "overview";
  const activeFinding =
    route.name === "issue" ? result?.findings.find((f) => f.id === route.id) ?? null : null;

  return (
    <>
      <Shell
        user={user}
        repoLabel={repoLabel}
        repoSub={result ? `Score ${result.score} · scanned ${timeAgo(result.scanned_at)}` : null}
        view={shellView}
        issueCount={result?.finding_count ?? null}
        fixCount={fixCount}
        promptActivity={promptActivity}
        onNavigate={(view) => navigate(view === "issues" ? "/app/issues" : view === "fixes" ? "/app/fixes" : "/app")}
        onSignOut={() => void handleSignOut()}
        onOpenSonar={() => openSonar()}
      >
        {scanNotice && (
          <div className="page" style={{ marginBottom: 4 }}>
            <div className={`notice ${scanNotice.startsWith("Re-scanned") ? "warning" : "danger"}`} style={{ marginBottom: 18 }}>
              {scanNotice}
            </div>
          </div>
        )}

        {!result && (
          <OnboardingWizard userName={user.name} onComplete={handleOnboardingComplete} />
        )}

        {result && route.name === "app" && (
          <Dashboard
            result={result}
            repoLabel={repoLabel ?? result.repository}
            drift={drift}
            onOpenIssue={openIssue}
            onOpenSonar={openSonar}
            onRescan={() => void handleRescan()}
            onAddRepo={handleAddRepo}
            onShowAllIssues={() => navigate("/app/issues")}
          />
        )}

        {result && route.name === "issues" && (
          <IssuesView result={result} onOpenIssue={openIssue} />
        )}

        {result && route.name === "fixes" && (
          <FixesView repoLabel={repoLabel ?? result.repository} />
        )}

        {result && route.name === "issue" && activeFinding && (
          <IssueDetail
            finding={activeFinding}
            scanId={result.scan_id}
            repository={repoLabel ?? result.repository}
            currentScore={result.score}
            aiReady={aiReady}
            aiProvider={aiProvider || undefined}
            aiApiKey={aiKey || undefined}
            onBack={() => navigate("/app/issues")}
            onAskSonar={openSonar}
            onPromptCopied={() => setPromptTick((t) => t + 1)}
          />
        )}

        {result && route.name === "issue" && !activeFinding && (
          <div className="page">
            <div className="empty-panel">
              That issue isn&rsquo;t in the current scan anymore.
              <div style={{ marginTop: 14 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => navigate("/app/issues")}>
                  Back to all issues
                </button>
              </div>
            </div>
          </div>
        )}

        {rescanning && (
          <div className="page">
            <div className="notice warning"><b>Re-scan running…</b>Sonar is reading your repo again. This page will update when it lands.</div>
          </div>
        )}
      </Shell>

      {!sonarOpen && <SonarFab onOpen={() => setSonarOpen(true)} />}
      <AskSonarDrawer
        open={sonarOpen}
        onClose={() => setSonarOpen(false)}
        scanId={result?.scan_id ?? null}
        repoLabel={repoLabel}
        findings={result?.findings ?? []}
        providers={providers}
        providersError={providersError}
        initialQuestion={sonarQuestion}
        onConsumeInitialQuestion={() => setSonarQuestion(null)}
        onOpenIssue={openIssue}
        providerName={aiProvider}
        apiKey={aiKey}
        onProviderChange={setAiProvider}
        onApiKeyChange={setAiKey}
      />
    </>
  );
}
