/**
 * ScanTerminal — truthful scan progress as a terminal readout.
 *
 * Every line is a real step reported by the scan-job worker, printed in
 * arrival order. When a newer step arrives the previous line is marked
 * done; nothing is invented, no filler captions rotate underneath.
 */

import { useEffect, useRef, useState } from "react";
import type { ScanJobState } from "../api/scanJobs";

interface ScanTerminalProps {
  job: ScanJobState | null;
  repoLabel?: string | null;
}

interface TermLine {
  text: string;
  done: boolean;
}

function commandLine(repoLabel?: string | null): TermLine {
  return { text: `$ sonar scan ${repoLabel || "repository"}`, done: true };
}

export function ScanTerminal({ job, repoLabel }: ScanTerminalProps) {
  const [lines, setLines] = useState<TermLine[]>(() => [commandLine(repoLabel)]);
  const bodyRef = useRef<HTMLDivElement>(null);
  const lastStepRef = useRef<string | null>(null);
  const jobNull = job === null;

  // A null job means a scan is (re)starting: reset to the command line.
  useEffect(() => {
    if (jobNull) {
      lastStepRef.current = null;
      setLines([commandLine(repoLabel)]);
    }
  }, [jobNull, repoLabel]);

  useEffect(() => {
    if (!job) return;
    if (job.status === "error") {
      const errText = `error: ${job.error || "something went wrong."}`;
      lastStepRef.current = errText;
      setLines((prev) => {
        const next = prev.map((l) => ({ ...l, done: true }));
        if (next[next.length - 1]?.text !== errText) {
          next.push({ text: errText, done: true });
        }
        return next;
      });
      return;
    }
    const step = job.step;
    if (step && step !== lastStepRef.current) {
      lastStepRef.current = step;
      setLines((prev) => [
        ...prev.map((l) => ({ ...l, done: true })),
        { text: step, done: job.status === "done" },
      ]);
    } else if (job.status === "done") {
      setLines((prev) => prev.map((l) => ({ ...l, done: true })));
    }
  }, [job]);

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="scan-terminal" role="log" aria-live="polite" aria-label="Scan progress">
      <div className="scan-terminal-body" ref={bodyRef}>
        {lines.map((line, i) => (
          <div key={i} className="scan-terminal-line">
            <span className="scan-terminal-mark" aria-hidden="true">
              {line.done ? "✓" : "›"}
            </span>
            <span className={line.done ? undefined : "scan-terminal-active"}>
              {line.text}
              {!line.done && <span className="scan-terminal-cursor" aria-hidden="true" />}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
