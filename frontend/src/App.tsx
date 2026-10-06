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
import { assertBillingUrl, stripSensitiveKeys } from "./utils/security";
import { fetchMe, logout } from "./api/auth";
import type { User } from "./api/auth";
import { fetchAiProviders } from "./api/askSonar";
import type { AiProvider } from "./api/askSonar";
import { PENDING_CHECKOUT_TIER_KEY, fetchBillingStatus, isCheckoutTier, openPortal } from "./api/billing";
import type { BillingStatus } from "./api/billing";
import { fetchComplianceStatus, reportGpc } from "./api/compliance";
import type { ComplianceStatus } from "./api/compliance";
import { isQuotaError } from "./api/errors";
import type { ApiError, QuotaErrorBody } from "./api/errors";
import { createScanJob, pollScanJob } from "./api/scanJobs";
import type { ScanJobState } from "./api/scanJobs";
import { fetchFixLog } from "./api/outcomes";
import { fetchPromptStatus } from "./api/prompts";
import { AskSonarDrawer } from "./components/AskSonarDrawer";
import { AgeGate } from "./components/AgeGate";
import { Dashboard } from "./components/Dashboard";
import { FixesView } from "./components/FixesView";
import { IssueDetail } from "./components/IssueDetail";
import { IssuesView } from "./components/IssuesView";
import { LandingPage } from "./components/LandingPage";
import { LegalPage } from "./components/LegalPage";
import type { LegalPageId } from "./components/LegalPage";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { PricingView } from "./components/PricingView";
import { UpgradeNudge } from "./components/UpgradeNudge";
import { Shell, SonarFab } from "./components/Shell";
import type { ShellView } from "./components/Shell";
import { ScanAnimation } from "./components/ScanAnimation";
import { timeAgo } from "./copy";

type Route =
  | { name: "landing" }
  | { name: "app" }
  | { name: "issues" }
  | { name: "issue"; id: string }
  | { name: "fixes" }
  | { name: "pricing" }
  | { name: "legal"; page: LegalPageId };

const LAST_SCAN_KEY = "code-sonar:last-scan";

function parseRoute(): Route {
  const hash = window.location.hash.replace(/^#/, "");
  if (window.location.pathname.startsWith("/app") && (hash === "" || hash === "/")) {
    return { name: "app" };
  }
  if (hash === "" || hash === "/") return { name: "landing" };
  if (hash === "/pricing") return { name: "pricing" };
  if (hash === "/legal/terms") return { name: "legal", page: "terms" };
  if (hash === "/legal/privacy") return { name: "legal", page: "privacy" };
  if (hash === "/legal/accessibility") return { name: "legal", page: "accessibility" };
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
  /** Local scan-over-scan diff (score delta + fixed/new counts), computed
   *  from the previous in-memory scan. Used when the backend drift API has
   *  no history to compare (e.g. after a server-side data reset). */
  const [scanDiff, setScanDiff] = useState<{
    scoreDelta: number;
    fixedCount: number;
    newCount: number;
  } | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [rescanJob, setRescanJob] = useState<ScanJobState | null>(null);
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
  // Billing: plan + usage for the sidebar quota block and pricing page.
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [billingLoading, setBillingLoading] = useState(false);
  /** Bumped after scans/asks complete so the usage block refreshes. */
  const [usageTick, setUsageTick] = useState(0);
  /** Stripe redirect banner: billing=success|cancelled in the query string. */
  const [billingBanner, setBillingBanner] = useState<"success" | "cancelled" | null>(null);
  /** 402 quota nudge modal payload. */
  const [quotaNudge, setQuotaNudge] = useState<{
    kind: "scans" | "ask_sonar";
    plan: string;
    limit: number;
    used: number;
  } | null>(null);
  const [portalError, setPortalError] = useState<string | null>(null);
  /** Pre-launch compliance: age gate, marketing opt-in, GPC. */
  const [compliance, setCompliance] = useState<ComplianceStatus | null>(null);
  const [complianceChecked, setComplianceChecked] = useState(false);

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

  // Billing status: plan + usage for the sidebar quota block and pricing.
  // Refreshed on navigation and whenever usage may have changed (usageTick).
  useEffect(() => {
    if (!user) {
      setBilling(null);
      return;
    }
    let cancelled = false;
    setBillingLoading(true);
    fetchBillingStatus()
      .then((status) => {
        if (!cancelled) setBilling(status);
      })
      .catch(() => {
        // Billing is informational; the app works without it.
        if (!cancelled) setBilling(null);
      })
      .finally(() => {
        if (!cancelled) setBillingLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user, route.name, usageTick]);

  // Stripe redirect: {site}/app?billing=success (or /pricing?billing=cancelled).
  // Hash routing is unaffected; read the query string once on mount and clear it.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("billing");
    if (result === "success" || result === "cancelled") {
      setBillingBanner(result);
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
      // A successful payment may have changed the plan — refresh usage.
      if (result === "success") setUsageTick((t) => t + 1);
    }
  }, []);

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

  // Global Privacy Control: honor it once on mount, signed in or not.
  // Fire-and-forget — a failed report must never break the page.
  useEffect(() => {
    if ((navigator as unknown as { globalPrivacyControl?: boolean }).globalPrivacyControl === true) {
      void reportGpc().catch(() => {
        // best-effort
      });
    }
  }, []);

  // Compliance status for signed-in users: drives the age gate.
  useEffect(() => {
    if (!user) {
      setCompliance(null);
      setComplianceChecked(false);
      return;
    }
    let cancelled = false;
    fetchComplianceStatus()
      .then((status) => {
        if (!cancelled) setCompliance(status);
      })
      .catch(() => {
        // Compliance is informational; without it we don't block the app —
        // but we also must not skip the gate, so leave compliance null and
        // mark the check done: the gate only shows on a known incomplete state.
        if (!cancelled) setCompliance(null);
      })
      .finally(() => {
        if (!cancelled) setComplianceChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  // Route guards.
  useEffect(() => {
    if (!authChecked) return;
    // Pricing and the legal pages are public: signed-out visitors can read them.
    if (!user && route.name !== "landing" && route.name !== "pricing" && route.name !== "legal") navigate("/");
    if (user && route.name === "landing") navigate("/app");
  }, [authChecked, user, route.name]);

  // Resume a pricing upgrade interrupted by sign-in. A signed-out visitor
  // who clicked a paid tier went through OAuth (which always lands on
  // /app); bring them back to #/pricing, where PricingView consumes the
  // pending tier and resumes their checkout.
  useEffect(() => {
    if (!authChecked || !user || route.name === "pricing") return;
    let pending: string | null = null;
    try {
      pending = window.sessionStorage.getItem(PENDING_CHECKOUT_TIER_KEY);
    } catch {
      return;
    }
    if (!isCheckoutTier(pending)) return;
    navigate("/pricing");
  }, [authChecked, user, route.name]);

  const persistScan = useCallback((next: ScanResponse, label: string) => {
    setResult(next);
    setRepoLabel(label);
    try {
      // Sanitize before persisting: localStorage is readable by any script
      // on the origin, so finding metadata goes through the sensitive-key
      // blocklist (the backend already redacts secret evidence server-side).
      const sanitized: ScanResponse = {
        ...next,
        findings: (next.findings ?? []).map((f) => ({
          ...f,
          metadata: stripSensitiveKeys(f.metadata),
        })),
      };
      window.localStorage.setItem(LAST_SCAN_KEY, JSON.stringify({ result: sanitized, repoLabel: label }));
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
      // The first scan consumed quota — refresh the sidebar usage block.
      setUsageTick((t) => t + 1);
      navigate("/app");
    },
    [persistScan, refreshDrift],
  );

  /**
   * Opens the 402 upgrade nudge when `e` is a billing quota error.
   * Returns true when the error was handled (callers should skip their
   * own error display in that case).
   */
  const handleQuotaError = useCallback((e: unknown): boolean => {
    if (!isQuotaError(e)) return false;
    const err = e as ApiError;
    const body = (err.body ?? {}) as QuotaErrorBody;
    setQuotaNudge({
      kind: err.quotaKind ?? "scans",
      plan: typeof body.plan === "string" ? body.plan : "",
      limit: typeof body.limit === "number" ? body.limit : 0,
      used: typeof body.used === "number" ? body.used : 0,
    });
    return true;
  }, []);

  const handleManageBilling = useCallback(async () => {
    setPortalError(null);
    try {
      window.location.href = assertBillingUrl(await openPortal());
    } catch (e) {
      setPortalError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const handleAskAnswered = useCallback(() => {
    // An answer consumed Ask Sonar quota — refresh the sidebar usage block.
    setUsageTick((t) => t + 1);
  }, []);

  const handleRescan = useCallback(async () => {
    if (!repoLabel || rescanning) return;
    setRescanning(true);
    setRescanJob(null);
    setScanNotice(null);
    // Capture the previous scan before it is replaced, so we can show a
    // local score-delta + fixed/new breakdown even when the backend has no
    // history to compare (e.g. after a server-side data reset).
    const previous = result;
    try {
      const jobId = await createScanJob(repoLabel);
      const { done } = pollScanJob(jobId, (state) => setRescanJob(state));
      const final = await done;
      if (final.status === "error") throw new Error(final.error ?? "Re-scan failed.");
      if (!final.result) throw new Error("Re-scan finished without a result.");
      if (previous) {
        const prevIds = new Set(previous.findings.map((f) => f.id));
        const nextIds = new Set(final.result.findings.map((f) => f.id));
        let fixedCount = 0;
        for (const id of prevIds) if (!nextIds.has(id)) fixedCount++;
        let newCount = 0;
        for (const id of nextIds) if (!prevIds.has(id)) newCount++;
        setScanDiff({
          scoreDelta: final.result.score - previous.score,
          fixedCount,
          newCount,
        });
      } else {
        setScanDiff(null);
      }
      persistScan(final.result, repoLabel);
      setScanNotice(`Re-scanned just now — score ${final.result.score}.`);
      void refreshDrift(repoLabel);
    } catch (e) {
      if (!handleQuotaError(e)) {
        setScanNotice(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setRescanning(false);
      // A scan consumed quota — refresh the sidebar usage block.
      setUsageTick((t) => t + 1);
    }
  }, [repoLabel, rescanning, result, persistScan, refreshDrift, handleQuotaError]);

  const handleAddRepo = useCallback(() => {
    setResult(null);
    setRepoLabel(null);
    setDrift(null);
    setScanDiff(null);
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

  if (!user) {
    // Pricing and the legal pages are public: signed-out visitors can read
    // the tiers and the draft legal documents.
    if (route.name === "legal") {
      return (
        <>
          <a className="skip-link" href="#main-content">Skip to content</a>
          <main className="main" id="main-content" tabIndex={-1}>
            <LegalPage page={route.page} />
          </main>
        </>
      );
    }
    if (route.name === "pricing") {
      return (
        <>
          <a className="skip-link" href="#main-content">Skip to content</a>
          <div className="main" id="main-content" tabIndex={-1}>
            <PricingView user={null} billing={null} billingLoading={false} />
          </div>
        </>
      );
    }
    return (
      <>
        <a className="skip-link" href="#main-content">Skip to content</a>
        <LandingPage />
      </>
    );
  }

  // The legal pages stay public for signed-in users too — reading them
  // never requires (or interrupts) a session.
  if (route.name === "legal") {
    return (
      <>
        <a className="skip-link" href="#main-content">Skip to content</a>
        <main className="main" id="main-content" tabIndex={-1}>
          <LegalPage page={route.page} />
        </main>
      </>
    );
  }

  // Wait for the compliance check before rendering the app, so the age
  // gate never flashes the dashboard underneath it.
  if (!complianceChecked) {
    return (
      <div className="loading-screen">
        <div className="loading-inner">
          <div className="spinner" />
          Waking up Sonar…
        </div>
      </div>
    );
  }

  if (compliance && !compliance.age_gate_completed) {
    return (
      <>
        <a className="skip-link" href="#main-content">Skip to content</a>
        <main className="main" id="main-content" tabIndex={-1}>
          <AgeGate
            onComplete={() => {
              // Re-read compliance status so the gate clears on its own.
              void fetchComplianceStatus()
                .then(setCompliance)
                .catch(() => {
                  // The gate itself succeeded; don't trap the user if the
                  // status read hiccups — fail open to the app.
                  setCompliance({ age_gate_completed: true, marketing_opt_in: false, gpc_honored: false });
                });
            }}
          />
        </main>
      </>
    );
  }

  const shellView: ShellView =
    route.name === "issues" || route.name === "issue"
      ? "issues"
      : route.name === "fixes"
        ? "fixes"
        : route.name === "pricing"
          ? "pricing"
          : "overview";
  const activeFinding =
    route.name === "issue" ? result?.findings.find((f) => f.id === route.id) ?? null : null;

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
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
        onRescan={() => void handleRescan()}
        rescanning={rescanning}
        billing={billing}
        onManageBilling={() => void handleManageBilling()}
      >
        {billingBanner && (
          <div className="page" style={{ marginBottom: 4 }}>
            <div className={`notice ${billingBanner === "success" ? "warning" : "danger"}`} style={{ marginBottom: 18 }}>
              <b>{billingBanner === "success" ? "Payment confirmed" : "Checkout cancelled"}</b>
              {billingBanner === "success"
                ? "Welcome to your new plan — your limits are already updated."
                : "No charge was made. Your current plan is unchanged."}
              <div style={{ marginTop: 10 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => setBillingBanner(null)}>
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        )}

        {portalError && (
          <div className="page" style={{ marginBottom: 4 }}>
            <div className="notice danger" style={{ marginBottom: 18 }}>
              <b>Couldn&rsquo;t open billing</b>
              {portalError}
              <div style={{ marginTop: 10 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => setPortalError(null)}>
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        )}

        {route.name === "pricing" && (
          <PricingView user={user} billing={billing} billingLoading={billingLoading} />
        )}

        {route.name !== "pricing" && scanNotice && (
          <div className="page" style={{ marginBottom: 4 }}>
            <div className={`notice ${scanNotice.startsWith("Re-scanned") ? "warning" : "danger"}`} style={{ marginBottom: 18 }}>
              {scanNotice}
            </div>
          </div>
        )}

        {route.name !== "pricing" && !result && (
          <OnboardingWizard
            userName={user.name}
            onComplete={handleOnboardingComplete}
            onQuotaExceeded={handleQuotaError}
          />
        )}

        {result && route.name === "app" && (
          <Dashboard
            result={result}
            repoLabel={repoLabel ?? result.repository}
            drift={drift}
            scanDiff={scanDiff}
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

        {route.name !== "pricing" && rescanning && (
          <div className="page">
            <div className="wizard-card">
              <ScanAnimation
                title="Re-scan running…"
                liveStep={rescanJob?.step}
                progress={rescanJob?.progress}
                repoLabel={repoLabel}
                note="nothing is changed in your repo"
              />
            </div>
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
        onQuotaExceeded={handleQuotaError}
        onAnswered={handleAskAnswered}
      />
      {quotaNudge && (
        <UpgradeNudge
          kind={quotaNudge.kind}
          plan={quotaNudge.plan}
          limit={quotaNudge.limit}
          used={quotaNudge.used}
          onDismiss={() => setQuotaNudge(null)}
          onSeePlans={() => {
            setQuotaNudge(null);
            navigate("/pricing");
          }}
        />
      )}
    </>
  );
}
