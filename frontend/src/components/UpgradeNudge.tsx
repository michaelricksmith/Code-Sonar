/**
 * UpgradeNudge — dismissible modal shown when an API call returns
 * 402 {"upgrade_required": true}. Points at #/pricing.
 */

interface UpgradeNudgeProps {
  kind: "scans" | "ask_sonar";
  plan: string;
  limit: number;
  used: number;
  onDismiss: () => void;
  onSeePlans: () => void;
}

export function UpgradeNudge({ kind, plan, limit, used, onDismiss, onSeePlans }: UpgradeNudgeProps) {
  const what = kind === "scans" ? "scans" : "Ask Sonar questions";
  const planLabel = plan ? plan.charAt(0).toUpperCase() + plan.slice(1) : "Free";
  return (
    <div className="modal-veil" onClick={onDismiss} role="presentation">
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-label="Usage limit reached"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-ico">⚡</div>
        <h3>You&rsquo;ve hit your {what} limit</h3>
        <p>
          You&rsquo;ve used {used} of {limit} {what} this month on the {planLabel} plan.
          Upgrade to keep {kind === "scans" ? "scanning" : "asking"} — paid plans
          start at $7/month.
        </p>
        <div className="modal-actions">
          <button className="btn btn-primary" onClick={onSeePlans}>
            See plans
          </button>
          <button className="btn btn-ghost" onClick={onDismiss}>
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
