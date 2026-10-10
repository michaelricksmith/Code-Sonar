/**
 * VitalsTrace — the code-health readout as a patient monitor.
 *
 * The trace is drawn from the scan's real findings: every spike is an
 * actual issue, with height set by severity (critical tallest). The same
 * findings always draw the same trace. When a rescan lands, the number
 * counts to the new score and the trace morphs to the new findings.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { Finding, Severity } from "../api/analyzers";
import { gradeForScore } from "../copy";

const SEV_HEIGHT: Record<Severity, number> = {
  critical: 44,
  error: 32,
  warning: 20,
  info: 10,
};
const SEV_RANK: Record<Severity, number> = {
  critical: 0,
  error: 1,
  warning: 2,
  info: 3,
};
const SLOTS = 6;
const PERIOD = 140;
const TILE = 4;
const Y0 = 62;
const SCORE_FLOOR = 300;

function slotHeights(findings: Finding[]): number[] {
  const sorted = [...findings].sort(
    (a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity] || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
  const heights = new Array<number>(SLOTS).fill(0);
  sorted.slice(0, SLOTS * 2).forEach((f, i) => {
    const slot = (i * 5) % SLOTS; // 5 is coprime with 6: spreads spikes evenly
    heights[slot] = Math.max(heights[slot], SEV_HEIGHT[f.severity] ?? 8);
  });
  return heights;
}

function buildPath(heights: number[]): string {
  const slotW = PERIOD / heights.length;
  let d = `M0,${Y0}`;
  for (let p = 0; p < TILE; p++) {
    const bx = p * PERIOD;
    heights.forEach((h, i) => {
      const cx = bx + i * slotW + slotW / 2;
      d += ` L${(cx - slotW * 0.32).toFixed(1)},${Y0}`;
      if (h > 0) {
        d +=
          ` L${cx.toFixed(1)},${Y0 - h}` +
          ` L${(cx + 3).toFixed(1)},${Y0}` +
          ` L${(cx + 6).toFixed(1)},${Y0 + Math.round(h * 0.4)}` +
          ` L${(cx + 9).toFixed(1)},${Y0}`;
      }
    });
    d += ` L${bx + PERIOD},${Y0}`;
  }
  return d;
}

interface VitalsTraceProps {
  score: number;
  findings: Finding[];
  width?: number;
  fadeId?: string;
}

export function VitalsTrace({ score, findings, width = 320, fadeId = "vitalsFade" }: VitalsTraceProps) {
  const [displayScore, setDisplayScore] = useState(SCORE_FLOOR);
  const [path, setPath] = useState(() => buildPath(new Array<number>(SLOTS).fill(0)));
  const anim = useRef({ score: SCORE_FLOOR, heights: new Array<number>(SLOTS).fill(0), raf: 0 });
  const first = useRef(true);

  // Deterministic identity for the findings set: re-morph only when it changes.
  const findingsKey = useMemo(() => findings.map((f) => f.id).sort().join(","), [findings]);

  useEffect(() => {
    const targetHeights = slotHeights(findings);
    const fromScore = anim.current.score;
    const fromHeights = [...anim.current.heights];
    const start = performance.now();
    const duration = first.current ? 1400 : 1000;
    first.current = false;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - t, 3);
      const s = Math.round(fromScore + (score - fromScore) * e);
      const h = targetHeights.map((th, i) => fromHeights[i] + (th - fromHeights[i]) * e);
      anim.current.score = s;
      anim.current.heights = h;
      setDisplayScore(s);
      setPath(buildPath(h));
      if (t < 1) anim.current.raf = requestAnimationFrame(tick);
    };
    anim.current.raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(anim.current.raf);
    // findingsKey gates re-runs; `findings` is read for the fresh data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [score, findingsKey]);

  const grade = gradeForScore(displayScore);
  const count = findings.length;

  return (
    <div className="vitals" style={{ width }}>
      <div className="vitals-head">
        <div className="vitals-scorewrap">
          <span className="vitals-num">{displayScore}</span>
          <span className="vitals-grade">Grade {grade}</span>
        </div>
        <div className="vitals-side">
          <div className="vitals-label">Code health</div>
          <div className="vitals-live">
            <i aria-hidden="true" />
            LIVE
          </div>
        </div>
      </div>
      <svg
        className="vitals-ekg"
        viewBox="0 0 420 110"
        preserveAspectRatio="none"
        role="img"
        aria-label={`Code health trace, score ${displayScore} out of 850`}
      >
        <defs>
          <linearGradient id={fadeId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#fafafa" />
            <stop offset="0.78" stopColor="#fafafa" />
            <stop offset="1" stopColor="#fafafa" stopOpacity="0" />
          </linearGradient>
        </defs>
        <g className="vitals-scroll">
          <path d={path} fill="none" stroke={`url(#${fadeId})`} strokeWidth={2} />
        </g>
      </svg>
      <div className="vitals-foot">
        {count === 0 ? "Clean trace — no issues found" : `${count} ${count === 1 ? "issue" : "issues"} on the monitor`}
      </div>
    </div>
  );
}
