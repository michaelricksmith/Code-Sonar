/**
 * Code Sonar — scan job API client (async scan flow for the onboarding wizard).
 *
 * New backend contract (built in parallel by a sibling agent):
 *   POST /api/scan-job {repo: "<owner/name>" or URL, branch?} → {job_id}
 *   GET  /api/scan-job/{job_id} →
 *     {status: queued|running|done|error, step: string, progress?: 0..1,
 *      result?: ScanResponse, error?: string}
 */

import type { ScanResponse } from "./analyzers";

export type ScanJobStatus = "queued" | "running" | "done" | "error";

export interface ScanJobState {
  status: ScanJobStatus;
  step: string;
  progress?: number;
  result?: ScanResponse;
  error?: string;
}

async function decode(res: Response, fallback: string): Promise<any> {
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail ?? data?.error ?? `${fallback} (HTTP ${res.status})`);
  return data;
}

export async function createScanJob(repo: string, branch?: string): Promise<string> {
  const res = await fetch("/api/scan-job", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(branch ? { repo, branch } : { repo }),
  });
  const data = await decode(res, "Could not start the scan");
  if (!data?.job_id) throw new Error("Scan job started but returned no job id.");
  return data.job_id as string;
}

export async function fetchScanJob(jobId: string): Promise<ScanJobState> {
  const res = await fetch(`/api/scan-job/${encodeURIComponent(jobId)}`, {
    credentials: "same-origin",
  });
  return (await decode(res, "Could not check scan progress")) as ScanJobState;
}

/**
 * Polls until the job reaches a terminal state, reporting each update.
 * Stops on done/error; surfaces transport errors to the caller.
 */
export function pollScanJob(
  jobId: string,
  onUpdate: (state: ScanJobState) => void,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): { cancel: () => void; done: Promise<ScanJobState> } {
  const intervalMs = opts.intervalMs ?? 1500;
  const timeoutMs = opts.timeoutMs ?? 10 * 60 * 1000;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const startedAt = Date.now();

  const cancel = () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
  };

  const done = (async (): Promise<ScanJobState> => {
    for (;;) {
      if (cancelled) throw new Error("Scan polling was cancelled.");
      if (Date.now() - startedAt > timeoutMs) {
        throw new Error("The scan is taking too long — try re-scanning.");
      }
      const state = await fetchScanJob(jobId);
      onUpdate(state);
      if (state.status === "done" || state.status === "error") return state;
      await new Promise<void>((resolve) => {
        timer = setTimeout(resolve, intervalMs);
      });
    }
  })();

  // Silence unhandled rejections for callers that only use onUpdate.
  done.catch(() => undefined);

  return { cancel, done };
}
