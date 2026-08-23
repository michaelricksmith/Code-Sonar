import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { fetchDrift, fetchHistory, postScan } from "@/api/analyzers";
import type {
  DriftResult,
  ScanResponse,
  ScanSummary,
} from "@/api/analyzers";
import { useFileFilter } from "@/state/useFileFilter";

const DEFAULT_REPO = "";

export function useScan() {
  const [repoPath, setRepoPath] = useState<string>(DEFAULT_REPO);
  const [scanResult, setScanResult] = useState<ScanResponse | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<ScanSummary[]>([]);
  const [driftResult, setDriftResult] = useState<DriftResult | null>(null);
  const { fileFilter, setFileFilter, clear } = useFileFilter();

  const refreshHistory = useCallback(async () => {
    try {
      const data = await fetchHistory();
      setHistory(data.scans ?? []);
    } catch {
      // history is best-effort
    }
  }, []);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const runScan = useCallback(async () => {
    if (!repoPath.trim()) return;
    setScanning(true);
    setError(null);
    clear();
    try {
      const result = await postScan(repoPath.trim());
      setScanResult(result);
      await refreshHistory();
    } catch (e) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.detail ?? e.message
        : e instanceof Error
          ? e.message
          : "Unknown error";
      setError(String(msg));
    } finally {
      setScanning(false);
    }
  }, [repoPath, refreshHistory, clear]);

  const comparePrevious = useCallback(async () => {
    if (!repoPath.trim()) return;
    setError(null);
    try {
      const drift = await fetchDrift({ repo_path: repoPath.trim() });
      setDriftResult(drift);
    } catch (e) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.detail ?? e.message
        : e instanceof Error
          ? e.message
          : "Unknown error";
      setError(String(msg));
    }
  }, [repoPath]);

  const hasScan = Boolean(scanResult);
  const hasHistory = history.length >= 2;

  return {
    repoPath,
    setRepoPath,
    scanResult,
    scanning,
    error,
    history,
    refreshHistory,
    runScan,
    comparePrevious,
    driftResult,
    hasScan,
    hasHistory,
    fileFilter,
    setFileFilter,
    clearFileFilter: clear,
  };
}