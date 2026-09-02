import type { Finding } from "../api/analyzers";

interface OverviewPrioritiesProps {
  findings: Finding[];
  totalFindings: number;
  onSelect: (finding: Finding) => void;
  onOpenSonar: (finding: Finding) => void;
  onShowAll: () => void;
}

function compactPath(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts.length > 4 ? `…/${parts.slice(-4).join("/")}` : path.replace(/\\/g, "/");
}

export function OverviewPriorities({ findings, totalFindings, onSelect, onOpenSonar, onShowAll }: OverviewPrioritiesProps) {
  const visible = findings.slice(0, 3);
  return (
    <section className="cs-overview-priorities" aria-labelledby="overview-priorities-title">
      <div className="cs-card-head">
        <div><span className="cs-kicker">Highest-impact evidence</span><h2 id="overview-priorities-title">Fix these signals first</h2></div>
        <button className="cs-link-button" onClick={onShowAll}>View all {totalFindings} findings →</button>
      </div>
      {visible.length === 0 ? <div className="cs-empty-panel">No priority findings in the current baseline.</div> : (
        <ol className="cs-signal-priority-list">
          {visible.map((finding, index) => (
            <li key={finding.id}>
              <div className="cs-signal-priority-rank"><span>Priority</span><strong>{String(index + 1).padStart(2, "0")}</strong></div>
              <div className="cs-signal-priority-content">
                <div className="cs-signal-priority-heading">
                  <strong title={finding.file_path}>{compactPath(finding.file_path)}</strong>
                  <span className={`cs-severity ${finding.severity}`}>{finding.severity} severity</span>
                </div>
                <p>{finding.message}</p>
                <div className="cs-signal-priority-meta">
                  <span><b>{finding.debt_points}</b> debt points</span>
                  <span>{finding.category}</span>
                  <span>{finding.analyzer}</span>
                </div>
              </div>
              <div className="cs-signal-priority-actions">
                <button className="cs-button primary" onClick={() => onSelect(finding)}>Investigate</button>
                <button className="cs-button ghost" onClick={() => onOpenSonar(finding)}>Ask Sonar</button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
