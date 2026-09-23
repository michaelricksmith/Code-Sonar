import type { CSSProperties } from "react";

import type { ScanResponse } from "../api/analyzers";

interface CreditReportHeroProps {
  result: ScanResponse;
  scoreDelta: number | null;
  onOpenSonar: () => void;
  onShowFindings: () => void;
}

const SEVERITY_SIGNALS = ["critical", "error", "warning", "info"] as const;

function scoreState(score: number): { tone: string; gradeLabel: string; riskLabel: string } {
  if (score >= 760) return { tone: "good", gradeLabel: "Excellent", riskLabel: "Low code-health risk" };
  if (score >= 650) return { tone: "fair", gradeLabel: "Healthy", riskLabel: "Moderate code-health risk" };
  if (score >= 550) return { tone: "warn", gradeLabel: "At risk", riskLabel: "Elevated code-health risk" };
  return { tone: "bad", gradeLabel: "High risk", riskLabel: "High code-health risk" };
}

function compactPath(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts.length > 4 ? `…/${parts.slice(-4).join("/")}` : path.replace(/\\/g, "/");
}

export function CreditReportHero({ result, scoreDelta, onOpenSonar, onShowFindings }: CreditReportHeroProps) {
  const state = scoreState(result.score);
  const progress = Math.max(0, Math.min(100, ((result.score - 300) / 550) * 100));
  const signalCounts = SEVERITY_SIGNALS
    .map((severity) => ({ severity, count: result.severity_distribution[severity] }))
    .filter((signal) => signal.count > 0);
  const blips = signalCounts.flatMap((signal, severityIndex) =>
    Array.from({ length: Math.min(2, signal.count) }, (_, blipIndex) => {
      const angle = (severityIndex * 83 + blipIndex * 47 + result.finding_count * 7) % 360;
      const radius = 23 + ((signal.count * 11 + severityIndex * 17 + blipIndex * 19) % 29);
      const radians = (angle * Math.PI) / 180;
      return {
        key: `${signal.severity}-${blipIndex}`,
        severity: signal.severity,
        x: 50 + Math.cos(radians) * radius,
        y: 50 + Math.sin(radians) * radius,
      };
    }),
  );
  const meterStyle = { "--score-progress": `${progress}%` } as CSSProperties;

  return (
    <section className={`cs-credit-hero ${state.tone}`} aria-labelledby="credit-report-title">
      <div className="cs-credit-grid">
        <div className="cs-sonar-field" aria-hidden="true" style={meterStyle}>
          <div className="cs-sonar-grid" />
          <div className="cs-sonar-ring ring-outer" />
          <div className="cs-sonar-ring ring-middle" />
          <div className="cs-sonar-ring ring-inner" />
          <div className="cs-sonar-sweep" />
          {blips.map((blip) => (
            <i
              className={`cs-sonar-blip ${blip.severity}`}
              key={blip.key}
              style={{ left: `${blip.x}%`, top: `${blip.y}%` }}
            />
          ))}
          <div
            className="cs-credit-meter"
            role="meter"
            aria-label={`Code Sonar health score ${result.score} out of 850, grade ${result.grade}, ${state.riskLabel}`}
            aria-valuemin={300}
            aria-valuemax={850}
            aria-valuenow={result.score}
            aria-valuetext={`${result.score} out of 850, grade ${result.grade}, ${state.riskLabel}`}
          >
            <span className="cs-credit-authority">Deterministic score</span>
            <strong>{result.score}</strong>
            <small>300 — 850</small>
          </div>
        </div>

        <div className="cs-credit-story">
          <span className="cs-kicker">Repository credit report</span>
          <div className="cs-credit-grade-line">
            <span>Grade</span><strong>{result.grade}</strong><b>{state.gradeLabel}</b>
          </div>
          <h1 id="credit-report-title">{compactPath(result.repository)} code health</h1>
          <p>{state.riskLabel}. The score is calculated only from deterministic analyzer evidence; Sonar remains advisory.</p>
          <div className="cs-credit-movement">
            <span className={scoreDelta === null ? "neutral" : scoreDelta >= 0 ? "positive" : "negative"}>
              {scoreDelta === null ? "First recorded baseline" : `${scoreDelta >= 0 ? "Improved" : "Declined"} ${Math.abs(scoreDelta)} points since the previous scan`}
            </span>
            <time dateTime={result.scanned_at}>Scanned {new Date(result.scanned_at).toLocaleString()}</time>
          </div>
          <div className="cs-credit-actions">
            <button className="cs-button primary" onClick={onShowFindings}>Review {result.finding_count} findings</button>
            <button className="cs-button ghost" onClick={onOpenSonar}>Ask Sonar to explain</button>
          </div>
        </div>

        <div className="cs-credit-signals" aria-label="Finding severity summary">
          {SEVERITY_SIGNALS.map((severity) => (
            <div key={severity} className={severity}>
              <span>{severity}</span>
              <strong>{result.severity_distribution[severity]}</strong>
              <small>{result.severity_distribution[severity] === 1 ? "finding" : "findings"}</small>
            </div>
          ))}
        </div>
      </div>

      <div className="cs-credit-ledger" aria-label="Scan provenance">
        <span><small>Repository</small><strong title={result.repository}>{compactPath(result.repository)}</strong></span>
        <span><small>Scan ID</small><strong>{result.scan_id ? result.scan_id.slice(0, 12) : "Unavailable"}</strong></span>
        <span><small>Debt measured</small><strong>{result.total_debt_points} points</strong></span>
        <span><small>Score authority</small><strong>Code Sonar</strong></span>
      </div>
    </section>
  );
}
