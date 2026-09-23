// Code Sonar — "What changed?" drift view.
//
// Checkpoint 6, Lane 3. Renders the drift result returned by the
// backend's `GET /api/drift` endpoint. Provides:
//
//   1. Score movement  (e.g. 785 -> 742, -43)
//   2. Debt movement   (e.g. 159 -> 203, +44)
//   3. Finding counts  (+8 new / -3 resolved / 2 worsened / 1 improved)
//   4. Drift filter chips (All / New / Resolved / Persistent / Worsened / Improved)
//   5. Per-finding state badges (NEW / RESOLVED / WORSENED / IMPROVED / UNCHANGED)
//   6. Category movement (+30 security / +12 maintainability / -4 testing)
//   7. Analyzer movement (+7 dead_code / +1 secrets / -3 comment_markers)

import type { DriftResult } from "../api/analyzers";

interface DriftViewProps {
  drift: DriftResult;
}

const CLASSIFICATION_ORDER = ["new", "resolved", "worsened", "improved", "persistent"] as const;
type Classification = (typeof CLASSIFICATION_ORDER)[number];

const CLASSIFICATION_LABEL: Record<Classification, string> = {
  new: "New",
  resolved: "Resolved",
  worsened: "Worsened",
  improved: "Improved",
  persistent: "Unchanged",
};

const CLASSIFICATION_TONE: Record<Classification, string> = {
  new: "border-sky-700/40 bg-sky-900/20 text-sky-100",
  resolved: "border-emerald-700/40 bg-emerald-900/20 text-emerald-100",
  worsened: "border-rose-700/40 bg-rose-900/20 text-rose-100",
  improved: "border-lime-700/40 bg-lime-900/20 text-lime-100",
  persistent: "border-slate-700 bg-slate-800/40 text-slate-200",
};

function signed(value: number): string {
  if (value > 0) return `+${value}`;
  return String(value);
}

function signedBold(value: number, positive: string, negative: string): string {
  if (value > 0) return positive;
  if (value < 0) return negative;
  return "±0";
}

export function DriftView({ drift }: DriftViewProps) {
  const s = drift.summary;

  // Movement numbers.
  const scoreMovement = signed(s.score_delta);
  const debtMovement = signed(s.debt_delta);

  // Movement tones.
  const scoreTone =
    s.score_delta > 0
      ? "text-emerald-400" // score up = better
      : s.score_delta < 0
        ? "text-rose-400"
        : "text-slate-300";
  const debtTone = s.debt_delta > 0 ? "text-rose-400" : s.debt_delta < 0 ? "text-emerald-400" : "text-slate-300";

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6 space-y-6">
      <header>
        <div className="text-xs uppercase tracking-wide text-slate-400">
          What changed since your last scan
        </div>
        <h2 className="mt-1 text-lg font-semibold text-slate-100">
          Drift since previous scan
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Baseline {s.baseline.scanned_at} ({s.baseline.scan_id.slice(0, 8)}) →{" "}
          Current {s.current.scanned_at} ({s.current.scan_id.slice(0, 8)})
        </p>
      </header>

      {/* Movement cards. */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-400">Score movement</div>
          <div className="mt-2 text-3xl font-bold text-slate-100">
            <span className={scoreTone}>{scoreMovement}</span>{" "}
            <span className="text-base text-slate-500">
              ({s.baseline.score} → {s.current.score})
            </span>
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-400">Debt movement</div>
          <div className="mt-2 text-3xl font-bold text-slate-100">
            <span className={debtTone}>{debtMovement}</span>{" "}
            <span className="text-base text-slate-500">
              ({s.baseline.total_debt_points} → {s.current.total_debt_points})
            </span>
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-400">Finding movement</div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <div className="text-sky-300">+{s.new_count} new</div>
            <div className="text-emerald-300">-{s.resolved_count} resolved</div>
            <div className="text-rose-300">{signed(s.worsened_count)} worsened</div>
            <div className="text-lime-300">{signed(s.improved_count)} improved</div>
            <div className="text-slate-400">{s.persistent_count} unchanged</div>
          </div>
        </div>
      </div>

      {/* Drift filter chips. */}
      <DriftFilters drift={drift} />

      {/* Per-classification finding lists. */}
      <div className="space-y-4">
        {(["new", "resolved", "worsened", "improved"] as const).map((cls) => {
          const findings = drift.findings.filter((f) => f.classification === cls);
          if (findings.length === 0) return null;
          return (
            <div
              key={cls}
              className={`rounded-lg border p-4 ${CLASSIFICATION_TONE[cls]}`}
            >
              <div className="text-xs uppercase tracking-wide">
                {CLASSIFICATION_LABEL[cls]} ({findings.length})
              </div>
              <ul className="mt-2 space-y-1 text-sm">
                {findings.slice(0, 25).map((f) => (
                  <li key={f.finding_id} className="flex items-baseline gap-2 font-mono text-xs">
                    <span className="truncate flex-1">{f.file_path}</span>
                    {f.line_start != null && <span>:{f.line_start}</span>}
                    <span className="rounded bg-slate-800/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                      {f.severity}
                    </span>
                    <span className="rounded bg-slate-800/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                      {f.category}
                    </span>
                    {f.risk_delta !== 0 && (
                      <span className="rounded bg-slate-800/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                        risk {signedBold(f.risk_delta, "↑", "↓")}
                      </span>
                    )}
                  </li>
                ))}
                {findings.length > 25 && (
                  <li className="text-xs text-slate-400">
                    … and {findings.length - 25} more
                  </li>
                )}
              </ul>
            </div>
          );
        })}
      </div>

      {/* Category movement. */}
      <DriftCategoryMovement drift={drift} />

      {/* Analyzer movement. */}
      <DriftAnalyzerMovement drift={drift} />
    </section>
  );
}

function DriftFilters({ drift }: { drift: DriftResult }) {
  const s = drift.summary;
  const chips: Array<{ label: string; count: number; tone: string }> = [
    {
      label: "All",
      count: drift.findings.length,
      tone: "border-slate-700 bg-slate-800/40 text-slate-200",
    },
    {
      label: "New",
      count: s.new_count,
      tone: "border-sky-700/40 bg-sky-900/20 text-sky-100",
    },
    {
      label: "Resolved",
      count: s.resolved_count,
      tone: "border-emerald-700/40 bg-emerald-900/20 text-emerald-100",
    },
    {
      label: "Worsened",
      count: s.worsened_count,
      tone: "border-rose-700/40 bg-rose-900/20 text-rose-100",
    },
    {
      label: "Improved",
      count: s.improved_count,
      tone: "border-lime-700/40 bg-lime-900/20 text-lime-100",
    },
    {
      label: "Unchanged",
      count: s.persistent_count,
      tone: "border-slate-700 bg-slate-800/40 text-slate-200",
    },
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((c) => (
        <span
          key={c.label}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${c.tone}`}
        >
          <span className="font-medium">{c.label}</span>
          <span className="rounded bg-slate-900/60 px-1.5 py-0.5 text-[10px]">{c.count}</span>
        </span>
      ))}
    </div>
  );
}

function DriftCategoryMovement({ drift }: { drift: DriftResult }) {
  const entries = Object.entries(drift.by_category).sort(
    (a, b) => Math.abs(b[1].debt_delta) - Math.abs(a[1].debt_delta),
  );
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">Category movement</div>
      <ul className="mt-2 space-y-1 text-sm">
        {entries.map(([cat, b]) => (
          <li key={cat} className="flex items-center gap-3 font-mono text-xs">
            <span className="flex-1 truncate text-slate-200">{cat}</span>
            <span
              className={
                b.debt_delta > 0
                  ? "text-rose-300"
                  : b.debt_delta < 0
                    ? "text-emerald-300"
                    : "text-slate-400"
              }
            >
              {signed(b.debt_delta)} debt
            </span>
            <span className="text-slate-500">
              +{b.new}/{b.resolved}/{b.worsened}/{b.improved}/{b.persistent}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DriftAnalyzerMovement({ drift }: { drift: DriftResult }) {
  const entries = Object.entries(drift.by_analyzer).sort(
    (a, b) => Math.abs(b[1].debt_delta) - Math.abs(a[1].debt_delta),
  );
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">Analyzer movement</div>
      <ul className="mt-2 space-y-1 text-sm">
        {entries.map(([az, b]) => (
          <li key={az} className="flex items-center gap-3 font-mono text-xs">
            <span className="flex-1 truncate text-slate-200">{az}</span>
            <span
              className={
                b.debt_delta > 0
                  ? "text-rose-300"
                  : b.debt_delta < 0
                    ? "text-emerald-300"
                    : "text-slate-400"
              }
            >
              {signed(b.debt_delta)} debt
            </span>
            <span className="text-slate-500">
              +{b.new}/{b.resolved}/{b.worsened}/{b.improved}/{b.persistent}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
