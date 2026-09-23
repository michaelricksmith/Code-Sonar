// Code Sonar — visible "why the score changed" callout.
//
// Lane 4 (Checkpoint 5): when a new analyzer materially changes the
// grade vs. the prior scan, the dashboard surfaces an explicit
// explanation of which analyzer contributed what. The MVP has no
// persisted prior-scan history, so the callout always explains the
// *current* scan's grade-defining contributions (which analyzer
// contributed the most debt points at the highest severities) and
// notes how many analyzers participated.

import type { ScanResponse } from "../api/analyzers";

interface ScoreChangeCalloutProps {
  result: ScanResponse;
  analyzerCount: number;
}

interface CategoryShare {
  category: string;
  count: number;
  share: number;
}

function topCategoryShare(result: ScanResponse): CategoryShare | null {
  const breakdown = result.findings_by_category;
  const entries = Object.entries(breakdown) as Array<[string, number]>;
  if (entries.length === 0) return null;
  const total = entries.reduce((acc, [, n]) => acc + n, 0);
  if (total === 0) return null;
  const sorted = entries.sort((a, b) => b[1] - a[1]);
  const [category, count] = sorted[0];
  return { category, count, share: count / total };
}

export function ScoreChangeCallout({
  result,
  analyzerCount,
}: ScoreChangeCalloutProps) {
  const top = topCategoryShare(result);
  const sourceBreakdown = result.findings_source_breakdown;
  const fixtureCount = (sourceBreakdown?.test ?? 0) + (sourceBreakdown?.fixture ?? 0);

  // Highlight when SECURITY is the dominant contributor AND there are
  // fixture-context findings, because the source-vs-fixture context
  // modifier is doing work that the user should know about.
  const securityDominant = top && top.category === "security" && top.share >= 0.4;
  const fixtureHasSecrets =
    fixtureCount > 0 && (result.findings_by_category["security"] ?? 0) > 0;

  const headlineTone = result.score >= 740
    ? "border-emerald-700/40 bg-emerald-900/20 text-emerald-100"
    : result.score >= 670
      ? "border-yellow-700/40 bg-yellow-900/20 text-yellow-100"
      : result.score >= 580
        ? "border-orange-700/40 bg-orange-900/20 text-orange-100"
        : "border-rose-700/40 bg-rose-900/20 text-rose-100";

  return (
    <section
      className={`rounded-lg border p-5 text-sm ${headlineTone}`}
      aria-label="Why the overall score is what it is"
    >
      <div className="text-xs uppercase tracking-wide opacity-80">
        Why the score is {result.score} ({result.grade})
      </div>

      <ul className="mt-3 space-y-2">
        <li>
          <strong>{analyzerCount}</strong>{" "}
          {analyzerCount === 1 ? "analyzer" : "analyzers"} contributed{" "}
          <strong>{result.finding_count}</strong> findings totalling{" "}
          <strong>{result.total_debt_points}</strong> raw debt points.
        </li>
        {top && (
          <li>
            Largest contributor: <code className="text-xs">{top.category}</code>{" "}
            with <strong>{top.count}</strong> findings (
            {(top.share * 100).toFixed(0)}% of total).
          </li>
        )}
        {fixtureHasSecrets && (
          <li className="text-xs">
            <strong>Fixture-context note:</strong>{" "}
            {fixtureCount} finding(s) live under{" "}
            <code className="text-xs">tests/</code>,{" "}
            <code className="text-xs">examples/</code>, or are{" "}
            <code className="text-xs">.env.example</code>-style documentation.
            Each one contributes only 25% as much to the score as the same
            finding in production source — the score reflects{" "}
            <strong>production</strong> debt, not the test fixtures.
          </li>
        )}
        {securityDominant && !fixtureHasSecrets && (
          <li className="text-xs">
            <strong>Security-driven grade:</strong>{" "}
            <code className="text-xs">security</code> findings dominate the
            score. Review the Findings table below for action items; severity
            ERROR or CRITICAL findings must be remediated before the score
            recovers.
          </li>
        )}
        {result.score === 850 && (
          <li className="text-xs text-emerald-200">
            Perfect score. No findings were produced by the analyzer pipeline.
          </li>
        )}
      </ul>
    </section>
  );
}
