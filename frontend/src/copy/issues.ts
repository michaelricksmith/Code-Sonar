/**
 * Shared issue-ranking + title helpers (kept out of component files so
 * react-refresh lint stays clean).
 */

import type { Finding, Severity } from "../api/analyzers";
import { analyzerLabel } from "./index";

const SEVERITY_WEIGHT: Record<Severity, number> = { critical: 8, error: 4, warning: 2, info: 1 };

/** Rank issues by severity, then fix-it points, then confidence. */
export function rankIssues(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => {
    const sev = SEVERITY_WEIGHT[b.severity] - SEVERITY_WEIGHT[a.severity];
    if (sev !== 0) return sev;
    const debt = b.debt_points - a.debt_points;
    if (debt !== 0) return debt;
    return b.confidence - a.confidence;
  });
}

/** Plain-language card title, e.g. "Exposed key or password in payments.js". */
export function issueCardTitle(finding: Finding): string {
  const base = finding.file_path.split(/[/\\]/).pop() ?? finding.file_path;
  if (finding.analyzer === "secrets") return `Exposed key or password in ${base}`;
  if (finding.analyzer === "comment_markers") return "Unfinished to-dos left in code";
  return `${analyzerLabel(finding.analyzer)} in ${base}`;
}
