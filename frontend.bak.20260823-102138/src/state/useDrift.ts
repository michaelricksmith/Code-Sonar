import { useCallback, useState } from "react";
import { fetchDrift } from "@/api/analyzers";
import type { DriftResult } from "@/api/analyzers";

export function useDrift(repoPath: string) {
  const [drift, setDrift] = useState<DriftResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (overrides?: { from_scan_id?: string; to_scan_id?: string }) => {
      if (!repoPath.trim()) {
        setError("Repository path is required.");
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const result = await fetchDrift(repoPath.trim(), overrides ?? {});
        setDrift(result);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [repoPath]
  );

  return { drift, loading, error, run };
}