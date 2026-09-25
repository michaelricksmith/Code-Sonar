/**
 * IssueDetail — finding detail + guided remediation (§2.4 screen 4,
 * mockup-remediation.html).
 *
 * Plain-language header, "What's going on" / "Why it matters", a numbered
 * fix checklist, and the "Fix this for me" consent → approve → live tracker
 * (Plan → Fix → Test → Rescan) → result flow.
 *
 * Reuses the existing remediation APIs UNCHANGED:
 * fetchRemediationPlan + approveAndRunRemediation (signed single-use
 * approvals). This is a reskin only.
 */

import { useEffect, useRef, useState } from "react";

import type { Finding } from "../api/analyzers";
import {
  approveAndRunRemediation,
  askSonar,
  fetchRemediationPlan,
} from "../api/askSonar";
import type { ApproveRemediationResponse, RemediationPlanResponse } from "../api/askSonar";
import {
  CATEGORY_AREA,
  SEVERITY_LABEL,
  analyzerLabel,
  checkSummary,
  confidenceLabel,
  copy,
  effortLabel,
  locationLabel,
  rawJson,
} from "../copy";
import { issueCardTitle } from "../copy/issues";
import { NerdsDetails } from "./NerdsDetails";

interface IssueDetailProps {
  finding: Finding;
  scanId: string | null;
  currentScore: number;
  /** true when an AI provider is configured for plain-language explanations */
  aiReady: boolean;
  aiProvider?: string;
  aiApiKey?: string;
  onBack: () => void;
  onAskSonar: (question: string) => void;
  onScoreChanged: (newScore: number) => void;
}

function requestId(scanId: string, findingId: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  return `ask-sonar-${scanId.slice(0, 10)}-${findingId.slice(0, 10)}-${suffix}`;
}

function riskIfIgnored(finding: Finding): string {
  if (finding.category === "security") return "Stolen credentials";
  if (finding.category === "complexity") return "Bugs in future changes";
  if (finding.category === "testing") return "Blind, risky changes";
  return "Slower, harder maintenance";
}

function plainHeadline(finding: Finding): string {
  if (finding.analyzer === "secrets") return "There's a live key sitting in your code";
  if (finding.analyzer === "comment_markers") return "Leftover to-dos are hiding in your code";
  return `${analyzerLabel(finding.analyzer)} — here's the fix`;
}

export function IssueDetail({
  finding,
  scanId,
  currentScore,
  aiReady,
  aiProvider,
  aiApiKey,
  onBack,
  onAskSonar,
  onScoreChanged,
}: IssueDetailProps) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [planResponse, setPlanResponse] = useState<RemediationPlanResponse | null>(null);
  const [workflowResponse, setWorkflowResponse] = useState<ApproveRemediationResponse | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planReviewed, setPlanReviewed] = useState(false);
  const askedRef = useRef(false);

  // Reset per issue.
  useEffect(() => {
    setExplanation(null);
    setPlanResponse(null);
    setWorkflowResponse(null);
    setError(null);
    setPlanReviewed(false);
    setLoadingPlan(false);
    setRunning(false);
    askedRef.current = false;
  }, [finding.id]);

  // Plain-language gloss from Ask Sonar when an AI provider is configured.
  useEffect(() => {
    if (!aiReady || !scanId || askedRef.current) return;
    askedRef.current = true;
    setExplaining(true);
    askSonar(
      {
        scanId,
        question:
          `Explain this code issue in plain language for someone who is new to coding. ` +
          `Keep it to two short paragraphs. First paragraph: what's going on. ` +
          `Second paragraph: why it matters for their app. The issue: "${finding.message}" ` +
          `in ${finding.file_path}${finding.line_start != null ? ` at line ${finding.line_start}` : ""}.`,
      },
      { provider: aiProvider, apiKey: aiApiKey },
    )
      .then((res) => setExplanation(res.answer.answer))
      .catch(() => setExplanation(null))
      .finally(() => setExplaining(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiReady, scanId, finding.id]);

  async function buildPlan(): Promise<void> {
    if (!scanId) return;
    setLoadingPlan(true);
    setError(null);
    setWorkflowResponse(null);
    try {
      setPlanResponse(await fetchRemediationPlan(scanId, finding.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingPlan(false);
    }
  }

  async function approveAndRun(): Promise<void> {
    if (!scanId || !planResponse) return;
    setRunning(true);
    setError(null);
    try {
      const response = await approveAndRunRemediation({
        requestId: requestId(scanId, finding.id),
        scanId,
        findingId: finding.id,
        planId: planResponse.plan.plan_id,
      });
      setWorkflowResponse(response);
      const delta = response.workflow.validation?.score_delta;
      if (typeof delta === "number") onScoreChanged(currentScore + delta);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const sevLabel = SEVERITY_LABEL[finding.severity];
  const sevTone = { critical: "critical", error: "attention", warning: "ok", info: "good" }[finding.severity];
  const effort = effortLabel(finding.remediation_effort);
  const isSecurity = finding.category === "security";
  const safeContext =
    typeof finding.metadata?.["safe_context"] === "string"
      ? (finding.metadata["safe_context"] as string)
      : null;

  const validation = workflowResponse?.workflow.validation ?? null;
  const execution = workflowResponse?.workflow.execution ?? null;
  const workflowCompleted = workflowResponse?.workflow.completed ?? false;
  const afterScore = validation ? currentScore + validation.score_delta : null;
  const plan = planResponse?.plan ?? null;

  const stepsDone = 1 + (plan ? 1 : 0) + (validation ? 2 : 0);
  const stepsTotal = 4;

  return (
    <div className="page">
      <button className="link back-link" onClick={onBack}>← Back to all {copy.findings}</button>

      <div className="detail-layout">
        <div>
          <div className="detail-head">
            <div>
              <span className={`sev-chip tone-${sevTone}`}>{sevLabel}</span>
              <span className="sev-chip tone-ok" style={{ marginLeft: 8, background: "#f4f1ea", color: "var(--muted)" }}>
                {CATEGORY_AREA[finding.category]}
              </span>
            </div>
            <h1>{plainHeadline(finding)}</h1>
            <p className="lede2">{issueCardTitle(finding)} — {confidenceLabel(finding.confidence)}.</p>
            <div>
              <span className="fileline mono">
                📄 {locationLabel(finding.file_path, finding.line_start, finding.line_end)}
              </span>
            </div>
          </div>

          <div className="explain-grid">
            <div className="explain-card">
              <div className="k">What&rsquo;s going on</div>
              {explaining && <p>Sonar is writing a plain-language explanation…</p>}
              {!explaining && explanation && <p>{explanation}</p>}
              {!explaining && !explanation && (
                <>
                  <h3>{analyzerLabel(finding.analyzer)}</h3>
                  <p>{checkSummary(finding.analyzer)} {finding.message}</p>
                </>
              )}
              {!aiReady && (
                <p className="ai-note">Connect an AI provider for a friendlier explanation — your code is never used to train it.</p>
              )}
            </div>
            <div className="explain-card warn">
              <div className="k">Why it matters</div>
              <h3>{riskIfIgnored(finding)}</h3>
              <p>
                {finding.suggestion ??
                  "Left alone, this kind of issue tends to get more expensive — every future change near it carries the risk with it."}
              </p>
            </div>
          </div>

          <div className="guide-card">
            <div className="guide-head">
              <h2>How to fix it — step by step</h2>
              <span className="pct">{stepsDone} of {stepsTotal} done</span>
            </div>
            <div className="pbar"><i style={{ width: `${(stepsDone / stepsTotal) * 100}%` }} /></div>

            <div className="gstep done">
              <div className="snum">✓</div>
              <div>
                <h4>Understand the problem</h4>
                <p>You&rsquo;ve read what&rsquo;s wrong and why it matters. <span className="done-tag">Done ✓</span></p>
              </div>
            </div>

            <div className={`gstep ${plan ? "done" : "current"}`}>
              <div className="snum">{plan ? "✓" : "2"}</div>
              <div>
                <h4>Review Sonar&rsquo;s fix plan</h4>
                {!plan && (
                  <>
                    <p>
                      Sonar writes a bounded plan: exactly which files change and how it will
                      verify the fix. Nothing runs until you approve it.
                    </p>
                    <div style={{ marginTop: 12 }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => void buildPlan()} disabled={loadingPlan || !scanId}>
                        {loadingPlan ? "Writing the plan…" : "✦ Write the fix plan"}
                      </button>
                    </div>
                    {!scanId && (
                      <p className="code-note">This scan wasn&rsquo;t saved, so Sonar can&rsquo;t bind a plan to it. Re-scan to enable guided fixes.</p>
                    )}
                  </>
                )}
                {plan && (
                  <>
                    <p><b>{plan.summary}</b></p>
                    <p style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>{plan.instruction}</p>
                    {!isSecurity && finding.evidence && (
                      <div className="diff">
                        <div className="dl ctx">{"// "}{finding.file_path} — what Sonar found</div>
                        <div className="dl ctx">{finding.evidence}</div>
                      </div>
                    )}
                    {isSecurity && (
                      <p className="code-note" style={{ marginTop: 12 }}>
                        The exact code isn&rsquo;t shown here because it may contain a live credential.{" "}
                        {safeContext ? "Safe surrounding context is shown below." : "Revoke the exposed value first, then fix."}
                      </p>
                    )}
                    {isSecurity && safeContext && (
                      <div className="diff">
                        <div className="dl ctx">{"// "}{finding.file_path} — safe surrounding context</div>
                        <div className="dl ctx">{safeContext}</div>
                      </div>
                    )}
                    <label className="checkline">
                      <input type="checkbox" checked={planReviewed} onChange={(e) => setPlanReviewed(e.target.checked)} />
                      <span>I&rsquo;ve reviewed the plan and I&rsquo;m happy with what it will change</span>
                    </label>
                    <span className="done-tag">Done ✓</span>
                  </>
                )}
              </div>
            </div>

            <div className={`gstep ${validation ? "done" : workflowResponse ? "" : plan ? "current" : ""}`}>
              <div className="snum">{validation ? "✓" : "3"}</div>
              <div>
                <h4>Let Sonar apply the fix</h4>
                <p>
                  {validation
                    ? "Sonar applied the fix in a safe copy of your code and verified it."
                    : workflowResponse
                      ? "Sonar ran the fix step, but testing and re-scoring didn't complete — see the result below."
                      : "Approve once and Sonar applies the fix, runs your tests, and re-scores — before anything touches your real files."}
                </p>
                {validation && <span className="done-tag">Done ✓</span>}
              </div>
            </div>

            <div className={`gstep ${validation ? "done" : ""}`}>
              <div className="snum">{validation ? "✓" : "4"}</div>
              <div>
                <h4>See your new score</h4>
                <p>
                  {validation
                    ? `Re-scan complete. Your score moved from ${currentScore} → ${afterScore}.`
                    : workflowResponse
                      ? "The re-scan didn't run this time. Use “Try the fix again” below to complete the remaining steps."
                      : "Once the fix lands, Sonar re-scores automatically and shows the new number here."}
                </p>
                {validation && <span className="done-tag">Done ✓</span>}
              </div>
            </div>
          </div>

          <div className="fix-panel">
            {!workflowResponse ? (
              <>
                <h2>✦ &nbsp;Want Sonar to do this for you?</h2>
                <p>
                  Approve once and Sonar will apply the fix in a <b>safe copy</b> of your code,
                  run your tests, and re-score — <b>before anything touches your real files.</b>{" "}
                  You review the result and decide what merges.
                </p>
                <div className="fix-list">
                  <div><span className="ok">✓</span><span>Only touches <b>&nbsp;{(plan?.expected_files ?? [finding.file_path]).join(", ")}</b></span></div>
                  <div><span className="ok">✓</span><span>Runs your test suite before and after</span></div>
                  <div><span className="ok">✓</span><span>Nothing commits, pushes, or merges without you</span></div>
                </div>
                {error && (
                  <div className="notice danger" style={{ position: "relative", marginTop: 16 }}>
                    <b>Something went wrong</b>{error}
                  </div>
                )}
                <button
                  className="btn btn-fix"
                  onClick={() => void (plan ? approveAndRun() : buildPlan().then(() => undefined))}
                  disabled={running || loadingPlan || !scanId || (plan != null && !planReviewed)}
                >
                  {running ? "Sonar is fixing it…" : loadingPlan ? "Writing the plan…" : plan ? "Approve & fix this for me →" : "Fix this for me →"}
                </button>
                {plan && !planReviewed && (
                  <p style={{ fontSize: 12.5, marginTop: 10 }}>Tick the &ldquo;I&rsquo;ve reviewed the plan&rdquo; box above to enable approval.</p>
                )}
              </>
            ) : (
              <>
                <h2>{validation?.finding_resolved ? "Fixed ✓" : workflowCompleted ? "Run finished" : "Fix didn't complete"}</h2>
                <div className="tracker" aria-label="Fix progress">
                  {["Plan", "Fix", "Test", "Rescan"].map((label, i) => {
                    const cls = i < 2 || validation ? "finished" : i === 2 && running ? "doing" : "";
                    return (
                      <div key={label} className={`track-step ${cls}`}>
                        <div className="tdot">{cls === "finished" ? "✓" : i + 1}</div>
                        {label}
                      </div>
                    );
                  })}
                </div>
                {validation && (
                  <div className="result-banner">
                    <h3>{validation.finding_resolved ? `Fixed. Your score went from ${currentScore} → ${afterScore}.` : "The issue is still present."}</h3>
                    <p>
                      {validation.finding_resolved
                        ? `${validation.regression_detected ? "No regressions were detected" : "Tests passed with no regressions"}${validation.tests_passed == null ? " (test reporting not configured)" : ""}. Review the change and merge when you're ready.`
                        : "Sonar ran the fix but the issue is still there. Try the manual steps above, or ask Sonar what to try next."}
                    </p>
                    {validation.finding_resolved && <div className="score-move">{currentScore} → {afterScore}</div>}
                  </div>
                )}
                {!validation && execution && (
                  <div className="result-banner" style={{ marginTop: 12 }}>
                    <h3>
                      {execution.state === "FAILED"
                        ? "The fix ran into a problem."
                        : execution.state === "DRY_RUN"
                          ? "No changes were made."
                          : "The fix step didn't produce a result."}
                    </h3>
                    <p>{execution.summary || execution.error || "Sonar stopped before testing and re-scoring."}</p>
                    {execution.error && execution.summary && (
                      <p className="code-note" style={{ marginTop: 8 }}>{execution.error}</p>
                    )}
                    {execution.changed_files.length > 0 && (
                      <p style={{ marginTop: 8 }}>Files touched: <span className="mono">{execution.changed_files.join(", ")}</span></p>
                    )}
                  </div>
                )}
                <div style={{ marginTop: 16, position: "relative", display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {!validation && (
                    <button
                      className="btn btn-fix btn-sm"
                      onClick={() => void approveAndRun()}
                      disabled={running || !plan}
                    >
                      {running ? "Sonar is fixing it…" : "↻ Try the fix again"}
                    </button>
                  )}
                  <button className="btn btn-ghost btn-sm" style={{ background: "transparent", color: "#fff", borderColor: "#3A4450" }} onClick={() => { setPlanResponse(null); setWorkflowResponse(null); setPlanReviewed(false); }}>
                    Start over with a fresh plan
                  </button>
                </div>
              </>
            )}
          </div>

          <NerdsDetails>
            <div className="kv"><span>Issue id</span><span className="mono">{finding.id}</span></div>
            <div className="kv"><span>Rule</span><span className="mono">{finding.rule_id}</span></div>
            <div className="kv"><span>Check</span><span className="mono">{finding.analyzer}</span></div>
            <div className="kv"><span>Category</span><span className="mono">{finding.category}</span></div>
            <div className="kv"><span>Severity</span><span className="mono">{finding.severity}</span></div>
            <div className="kv"><span>Fix-it points</span><span className="mono">{finding.debt_points}</span></div>
            <div className="kv"><span>Symbol</span><span className="mono">{finding.symbol ?? "—"}</span></div>
            {Object.keys(finding.metadata ?? {}).length > 0 && (
              <div style={{ marginTop: 12 }}>
                <pre>{rawJson(finding.metadata)}</pre>
              </div>
            )}
          </NerdsDetails>
        </div>

        <div className="rail">
          <div className="rail-label">Impact</div>
          <div className="impact">
            {validation ? (
              <>
                <div className="big">{validation.score_delta > 0 ? `+${validation.score_delta}` : validation.score_delta}</div>
                <div className="cap">Actual score change from the fix.<br />{currentScore} → {afterScore}</div>
              </>
            ) : (
              <>
                <div className="big" style={{ color: "var(--muted)" }}>?</div>
                <div className="cap">Estimated impact appears after Sonar re-scores.<br />No guesswork — only measured numbers.</div>
              </>
            )}
          </div>
          <div className="impact">
            <div className="kv"><span>{confidenceLabel(0).split(":")[0]}</span><span>{Math.round(finding.confidence * 100)}%</span></div>
            <div className="kv"><span>Time to fix</span><span>{effort ?? "Varies"}</span></div>
            <div className="kv"><span>Risk if ignored</span><span style={{ color: "var(--bad)" }}>{riskIfIgnored(finding)}</span></div>
            <div className="kv"><span>Files touched</span><span>{plan ? plan.expected_files.length : 1}</span></div>
          </div>

          <div className="rail-label">Ask Sonar</div>
          <div className="impact">
            <div style={{ display: "grid", gap: 8 }}>
              <button className="suggest" onClick={() => onAskSonar(`Will fixing "${issueCardTitle(finding)}" break my app?`)}>Will this break my app?</button>
              <button className="suggest" onClick={() => onAskSonar(`Explain "${issueCardTitle(finding)}" like I'm new to coding.`)}>Explain this like I&rsquo;m new</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
