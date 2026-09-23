/**
 * Code Sonar — plain-language copy map (§2.3 of the approved design direction).
 *
 * This module sits between the API and the UI and translates every backend
 * term into human words for vibe coders. Nothing in the engine changes —
 * only what the user reads.
 *
 * Grade cutoffs here MUST match the scoring engine exactly
 * (backend/app/scoring/engine.py :: _score_to_grade):
 *   A >= 800 · B >= 740 · C >= 670 · D >= 580 · F below
 */

import type { Category, Severity } from "../api/analyzers";

/* ------------------------------------------------------------------ */
/* Grades                                                              */
/* ------------------------------------------------------------------ */

export type Grade = "A" | "B" | "C" | "D" | "F";

export const SCORE_MIN = 300;
export const SCORE_MAX = 850;

/** Engine-exact grade bands. Do not "improve" these without the engine. */
export function gradeForScore(score: number): Grade {
  if (score >= 800) return "A";
  if (score >= 740) return "B";
  if (score >= 670) return "C";
  if (score >= 580) return "D";
  return "F";
}

export const GRADE_WORDS: Record<Grade, string> = {
  A: "Excellent",
  B: "Good",
  C: "Fair",
  D: "Needs work",
  F: "At risk",
};

export const GRADE_TONE: Record<Grade, "good" | "ok" | "attention" | "critical"> = {
  A: "good",
  B: "good",
  C: "ok",
  D: "attention",
  F: "critical",
};

/* ------------------------------------------------------------------ */
/* Severity: critical/error/warning/info → Urgent/High/Medium/Low       */
/* ------------------------------------------------------------------ */

export const SEVERITY_LABEL: Record<Severity, "Urgent" | "High" | "Medium" | "Low"> = {
  critical: "Urgent",
  error: "High",
  warning: "Medium",
  info: "Low",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "error", "warning", "info"];

export function severityRankIndex(severity: Severity): number {
  return SEVERITY_ORDER.indexOf(severity);
}

/* ------------------------------------------------------------------ */
/* Analyzers ("checks") → plain labels                                 */
/* ------------------------------------------------------------------ */

export const ANALYZER_LABELS: Record<string, string> = {
  cyclomatic_complexity: "Tangled logic",
  nesting_depth: "Deeply nested code",
  comment_markers: "Unfinished to-dos left in code",
  oversized_files: "A file doing too much",
  oversized_functions: "An overworked function",
  secrets: "Exposed password / key",
  testing_debt: "No tests covering this",
  dead_code: "Unused code",
};

/** Human label for a backend analyzer id. Falls back to a readable id. */
export function analyzerLabel(analyzer: string): string {
  return ANALYZER_LABELS[analyzer] ?? analyzer.replace(/_/g, " ");
}

/**
 * One-line plain-language summary of what a check means for the user.
 * These are static glosses of the check type (not per-issue AI text),
 * safe to show on every issue card.
 */
export function checkSummary(analyzer: string): string {
  switch (analyzer) {
    case "secrets":
      return "A secret key or password is sitting in your code where anyone with access to the file can read it.";
    case "cyclomatic_complexity":
      return "One function has too many decision paths — every future change here risks breaking something.";
    case "nesting_depth":
      return "Code nested too deep to follow easily — hard to read, easy to break.";
    case "comment_markers":
      return "Leftover to-do notes from earlier builds. Harmless today, but they hide real work.";
    case "oversized_files":
      return "This file is doing too much — hard to navigate and risky to change.";
    case "oversized_functions":
      return "This function is doing too much at once — splitting it makes it safe to touch.";
    case "testing_debt":
      return "This code has no tests covering it — changes here go in blind.";
    case "dead_code":
      return "Unused code that still gets read, maintained, and confuses people.";
    default:
      return "Sonar flagged something worth a look here.";
  }
}

/* ------------------------------------------------------------------ */
/* Categories → health areas (dashboard "Health by area")              */
/*                                                                     */
/* Backend categories: complexity, staleness, security, duplication,   */
/* testing, maintainability. The dashboard shows four friendly areas.   */
/* ------------------------------------------------------------------ */

export type HealthArea = "Security" | "Complexity" | "Tests" | "Tidy-up";

export const CATEGORY_AREA: Record<Category, HealthArea> = {
  security: "Security",
  complexity: "Complexity",
  testing: "Tests",
  staleness: "Tidy-up",
  duplication: "Tidy-up",
  maintainability: "Tidy-up",
};

export const AREA_ORDER: HealthArea[] = ["Security", "Complexity", "Tests", "Tidy-up"];

export const AREA_NOTE: Record<HealthArea, string> = {
  Security: "Exposed keys and unsafe patterns",
  Complexity: "Tangled logic and hard-to-read code",
  Tests: "Code with no tests covering it",
  "Tidy-up": "Leftover to-dos and unused code",
};

/* ------------------------------------------------------------------ */
/* Generic jargon map                                                  */
/* ------------------------------------------------------------------ */

export const copy = {
  finding: "issue",
  findings: "issues",
  analyzer: "check",
  analyzers: "checks",
  remediation: "fix",
  drift: "what changed",
  riskHotspot: "riskiest file",
  confidence: "how sure we are",
  baseline: "first scan",
  technicalDebt: "fix-it points",
};

/* ------------------------------------------------------------------ */
/* Verdicts, deltas, formatting                                        */
/* ------------------------------------------------------------------ */

/** Plain-language verdict for the dashboard hero. */
export function verdictForScore(score: number, urgentCount: number): string {
  const grade = gradeForScore(score);
  if (grade === "A") {
    return "Your code is in great shape — keep it up. We'll flag anything new before it becomes a problem.";
  }
  if (grade === "B") {
    return "Your code is in good shape. A little cleanup would push it into the top tier.";
  }
  if (grade === "C") {
    return urgentCount > 0
      ? `Your app is in fair shape — ${urgentCount === 1 ? "1 urgent issue is" : `${urgentCount} urgent issues are`} doing most of the damage.`
      : "Your app is in fair shape — a handful of issues are dragging it down.";
  }
  if (grade === "D") {
    return "Your code needs some attention. The good news: a few focused fixes can move this number a lot.";
  }
  return "Your code is at risk right now. Start with the urgent issues below — each fix moves the score.";
}

/** "+24 since last scan" / "−12 since last scan" / "Same as last scan". */
export function deltaText(delta: number): string {
  if (delta > 0) return `▲ +${delta} since last scan`;
  if (delta < 0) return `▼ ${delta} since last scan`;
  return "No change since last scan";
}

/** "How sure we are: 98%" */
export function confidenceLabel(confidence: number): string {
  return `${copy.confidence}: ${Math.round(confidence * 100)}%`;
}

/** "~10 min to fix" — only used when the engine provided an effort estimate. */
export function effortLabel(remediationEffort: string | null): string | null {
  if (!remediationEffort) return null;
  return remediationEffort.startsWith("~") ? remediationEffort : `~${remediationEffort}`;
}

/** File line reference, e.g. "lib/payments.js · line 12". */
export function locationLabel(
  filePath: string,
  lineStart: number | null,
  lineEnd: number | null,
): string {
  if (lineStart == null) return filePath;
  if (lineEnd != null && lineEnd !== lineStart) return `${filePath} · lines ${lineStart}–${lineEnd}`;
  return `${filePath} · line ${lineStart}`;
}

/** Render a raw-metadata record as readable JSON (for "Details for nerds"). */
export function rawJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Short relative-ish time label for "scored 2 hours ago". */
export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "recently";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
