/**
 * ScanAnimation — shared animated scan progress for the first scan and
 * re-scans. Sonar-ring animation with rotating human-readable step
 * captions and a live progress bar. When the backend reports a live step
 * it wins; otherwise the captions keep rotating on a timer so the UI
 * never looks stuck while a scan is running.
 */

import { useEffect, useState } from "react";

const FALLBACK_STEPS = ["Reading your files…", "Running 8 checks…", "Tallying your score…"];

interface ScanAnimationProps {
  title: string;
  /** Live step from the scan job, when the backend reports one. */
  liveStep?: string | null;
  /** 0..1 progress from the scan job. Defaults to a small nonzero value. */
  progress?: number | null;
  repoLabel?: string | null;
  note?: string;
}

export function ScanAnimation({ title, liveStep, progress, repoLabel, note }: ScanAnimationProps) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (liveStep) return;
    const timer = setInterval(() => setTick((n) => n + 1), 2600);
    return () => clearInterval(timer);
  }, [liveStep]);

  const stepText = liveStep || FALLBACK_STEPS[tick % FALLBACK_STEPS.length];
  const pct = Math.round((progress ?? 0.15) * 100);

  return (
    <>
      <h2>{title}</h2>
      <div className="sonar-ring-wrap">
        <div className="sonar-ring" aria-hidden="true">
          <div className="ring r1" />
          <div className="ring r2" />
          <div className="ring r3" />
          <div className="core" />
        </div>
        <div className="scan-step">{stepText}</div>
        <div className="scan-sub">
          {repoLabel ? <span className="mono">{repoLabel}</span> : "Preparing…"}
          {note ? ` · ${note}` : null}
        </div>
        <div
          className="scan-progress"
          role="progressbar"
          aria-label="Scan progress"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
    </>
  );
}
