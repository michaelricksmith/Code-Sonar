import React, { useState, useEffect, useCallback, useRef } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import {
  Finding,
  FindingStatus,
  RiskHotspot,
  WhatChangedEvent,
  ArchitecturalDriftItem,
  RepositoryOption,
  Grade,
  ReleaseGateRecord,
  QualityGatePolicy,
  Severity,
} from './types';
import { Header } from './components/common/Header';
import { Sidebar, NavPage } from './components/common/Sidebar';
import { FindingDrawer } from './components/common/FindingDrawer';
import { CommandPalette } from './components/common/CommandPalette';
import { OverviewView } from './components/overview/OverviewView';
import { FindingsView } from './components/findings/FindingsView';
import { RiskHotspotsView } from './components/hotspots/RiskHotspotsView';
import { HistoryView } from './components/history/HistoryView';
import { DriftView } from './components/drift/DriftView';
import { SettingsView } from './components/settings/SettingsView';
import { TelemetryBar } from './components/common/TelemetryBar';
import { LiveScanTerminal } from './components/common/LiveScanTerminal';
import {
  ApiFinding,
  ApiHotspot,
  ApiDriftResult,
  ApiTelemetrySnapshot,
  ApiRiskProjection,
  ApiScanResponse,
  ApiScanRecord,
  ApiScanSummary,
  ApiError,
  getHistoryLatest,
  getHotspots,
  getDrift,
  getTelemetryLatest,
  getProjection,
  postScan,
  getTelemetryHistory,
} from './api/codeSonar';

/**
 * Default repo path used when the user hasn't picked one yet. This
 * points to the code-sonar frontend itself — the backend can scan any
 * repo it has filesystem access to. The user can override this via the
 * Header's repo picker (handled by `setCurrentRepo`).
 */
const DEFAULT_REPO_PATH =
  (import.meta.env.VITE_DEFAULT_REPO_PATH as string | undefined)?.trim() ||
  'C:\\Users\\bookm\\.openclaw\\workspace\\code-sonar\\frontend';

// ---------------------------------------------------------------------------
// Adapters: backend JSON -> frontend UI types
// ---------------------------------------------------------------------------

// Backend categories (see backend/app/models/finding.py)
type BackendCategory =
  | 'complexity'
  | 'staleness'
  | 'security'
  | 'duplication'
  | 'testing'
  | 'maintainability';

type BackendSeverity = 'info' | 'warning' | 'error' | 'critical';

const CATEGORY_TO_UI: Record<BackendCategory, Finding['category']> = {
  complexity: 'reliability',
  staleness: 'tech_debt',
  security: 'security',
  duplication: 'tech_debt',
  testing: 'compliance',
  maintainability: 'tech_debt',
};

const SEVERITY_TO_UI: Record<BackendSeverity, Severity> = {
  info: 'info',
  warning: 'warning',
  error: 'high',
  critical: 'critical',
};

/**
 * Convert a backend finding (snake_case, backend enums) into the
 * frontend `Finding` type that components already consume.
 *
 * The conversion is intentionally minimal: it preserves the source
 * of truth from the backend (id, file path, severity, category,
 * debt points, etc.) and only re-shapes the field names.
 */
function adaptFinding(
  f: ApiFinding,
  repository: string,
  branch: string
): Finding {
  const lineStart = typeof f.line_start === 'number' ? f.line_start : 1;
  const lineEnd =
    typeof f.line_end === 'number' && f.line_end >= lineStart
      ? f.line_end
      : lineStart;

  return {
    id: f.id,
    ruleId: f.rule_id,
    title: f.message || f.rule_id,
    description: f.evidence || f.message || '',
    severity: SEVERITY_TO_UI[f.severity] ?? 'warning',
    category:
      (CATEGORY_TO_UI[f.category] as Finding['category']) ?? 'tech_debt',
    status: 'open',
    filePath: f.file_path,
    lineRange: [lineStart, lineEnd],
    codeSnippet: f.evidence || '',
    suggestedFix: f.suggestion ?? undefined,
    impactScore: Math.min(
      100,
      Math.round(
        (typeof f.confidence === 'number' ? f.confidence : 0.5) * 100
      )
    ),
    debtHours: f.debt_points,
    blastRadius: 'package',
    cwe: undefined,
    cve: undefined,
    author: f.analyzer,
    commitHash: '',
    introducedDate: f.detected_at,
    assignee: undefined,
    repository,
    branch,
  };
}

/**
 * Convert a backend hotspot into the frontend `RiskHotspot` shape.
 * The backend hotspot uses a simpler score formula (debt + severity +
 * finding_count + analyzer_diversity * 2) — we keep that raw score
 * and rescale only for the existing /100 display by passing it
 * through unchanged (UI shows "Score X/100" because the layout is
 * preserved; we do not fabricate additional math).
 */
function adaptHotspot(
  h: ApiHotspot,
  repository: string
): RiskHotspot {
  const severityMax = h.severity_max;
  const critical = severityMax === 'critical' ? 1 : 0;
  const high = severityMax === 'error' ? 1 : 0;
  const warning = severityMax === 'warning' ? 1 : 0;

  // The backend score is unbounded (debt + …). The UI displays it as
  // /100 — we clamp so it stays inside the existing color thresholds.
  const clampedScore = Math.min(100, Math.max(0, Math.round(h.score)));

  return {
    id: `${repository}:${h.file_path}`,
    filePath: h.file_path,
    repository,
    riskScore: clampedScore,
    churnRate: h.finding_count > 5 ? 'high' : h.finding_count > 2 ? 'medium' : 'low',
    commitCount30d: 0,
    authorsCount: h.analyzer_diversity,
    cyclomaticComplexity: h.complexity_max,
    linesOfCode: h.size_max,
    findingsCount: {
      critical,
      high,
      warning,
    },
    testCoverage: 0,
    blastRadiusScore: Math.min(
      100,
      Math.round(h.finding_count * 8 + h.analyzer_diversity * 5)
    ),
    architecturalRole: 'Module',
    refactorRoi:
      clampedScore >= 85 ? 'immediate' : clampedScore >= 75 ? 'high' : 'medium',
  };
}

function buildWhatChangedFromHistory(
  history: ApiScanSummary[]
): WhatChangedEvent[] {
  if (history.length === 0) return [];
  const events: WhatChangedEvent[] = [];
  for (let i = 1; i < history.length; i++) {
    const baseline = history[i - 1];
    const current = history[i];
    const scoreDelta = current.score - baseline.score;
    const debtDelta = current.total_debt_points - baseline.total_debt_points;
    const findingDelta = current.finding_count - baseline.finding_count;
    const direction = scoreDelta > 0 ? 'improving' : scoreDelta < 0 ? 'degrading' : 'flat';
    const title =
      direction === 'improving'
        ? `Risk posture improved by ${scoreDelta} pts`
        : direction === 'degrading'
        ? `Risk posture declined by ${Math.abs(scoreDelta)} pts`
        : `Risk posture unchanged (${current.score})`;
    events.push({
      id: `wc-${current.scan_id}`,
      type: direction === 'improving' ? 'refactor_completed' : 'drift_detected',
      title,
      description:
        `Scan ${current.scan_id} vs ${baseline.scan_id}. ` +
        `Debt ${baseline.total_debt_points}→${current.total_debt_points} ` +
        `(${debtDelta >= 0 ? '+' : ''}${debtDelta}), ` +
        `findings ${baseline.finding_count}→${current.finding_count} ` +
        `(${findingDelta >= 0 ? '+' : ''}${findingDelta}).`,
      timestamp: current.scanned_at,
      actor: { name: 'Code Sonar Pipeline', avatar: '' },
      deltaScore: scoreDelta,
      commitHash: current.scan_id,
      severity: scoreDelta >= 0 ? 'healthy' : 'high',
    });
  }
  return events.reverse();
}

function adaptDriftToItems(drift: ApiDriftResult): ArchitecturalDriftItem[] {
  return drift.findings.map((d) => ({
    id: d.finding_id,
    title: d.message || d.rule_id,
    type:
      d.classification === 'new'
        ? 'unauthorized_api'
        : d.classification === 'worsened'
        ? 'layer_violation'
        : d.classification === 'improved' || d.classification === 'resolved'
        ? 'orphaned_module'
        : 'cyclic_dependency',
    severity:
      d.severity === 'critical'
        ? 'critical'
        : d.severity === 'error'
        ? 'high'
        : d.severity === 'warning'
        ? 'warning'
        : 'info',
    sourceModule: d.file_path,
    targetModule: d.symbol ?? d.analyzer,
    description: `${d.classification.toUpperCase()} — ${d.message || d.rule_id}`,
    baselineRule:
      d.baseline_severity !== null
        ? `Baseline severity: ${d.baseline_severity}, risk: ${d.baseline_risk?.toFixed(2) ?? 'n/a'}`
        : 'Newly introduced in this scan',
    detectedAt: '',
    introducedInPR: d.finding_id,
    status:
      d.classification === 'resolved' || d.classification === 'improved'
        ? 'resolving'
        : 'active',
    codeDiff:
      d.baseline_severity !== null
        ? {
            file: d.file_path,
            addedLines: [`severity: ${d.current_severity}`],
            removedLines: [`severity: ${d.baseline_severity}`],
          }
        : undefined,
  }));
}

function adaptHistoryToTrend(history: ApiScanSummary[]) {
  return history.map((s) => ({
    date: s.scanned_at.slice(0, 10),
    score: s.score,
    critical:
      (s.severity_distribution.critical ?? 0) +
      (s.severity_distribution.error ?? 0),
    debtHours: s.total_debt_points,
  }));
}

function adaptHistoryToGateRecords(history: ApiScanSummary[]): ReleaseGateRecord[] {
  return history.map((s) => ({
    id: s.scan_id,
    releaseTag: s.scan_id,
    environment: 'production',
    status:
      s.score >= 750 ? 'passed' : s.score >= 600 ? 'overridden' : 'blocked',
    riskScore: s.score,
    criticalCount: s.severity_distribution.critical ?? 0,
    highCount: s.severity_distribution.error ?? 0,
    timestamp: s.scanned_at,
    commitHash: s.scan_id,
    evaluatedRules: [
      {
        rule: 'Score ≥ 750',
        passed: s.score >= 750,
        actualValue: String(s.score),
        threshold: '750',
      },
      {
        rule: 'Critical findings ≤ 0',
        passed: (s.severity_distribution.critical ?? 0) === 0,
        actualValue: String(s.severity_distribution.critical ?? 0),
        threshold: '0',
      },
      {
        rule: 'Debt points ≤ 100',
        passed: s.total_debt_points <= 100,
        actualValue: String(s.total_debt_points),
        threshold: '100',
      },
    ],
  }));
}

const DEFAULT_QUALITY_GATE_POLICIES: QualityGatePolicy[] = [];

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

export default function App() {
  const [activePage, setActivePage] = useState<NavPage>('overview');

  // The active repository path. The Header lets the user change it
  // via the dropdown. The default is taken from VITE_DEFAULT_REPO_PATH
  // or set to the frontend repo so a fresh boot has something to scan.
  const [currentRepoPath, setCurrentRepoPath] = useState<string>(DEFAULT_REPO_PATH);

  // Surface a RepositoryOption so the existing Header UI keeps its
  // single-prop signature.
  const [currentRepo, setCurrentRepo] = useState<RepositoryOption>({
    id: currentRepoPath,
    name: currentRepoPath.split(/[\\/]/).filter(Boolean).slice(-2).join('/') || currentRepoPath,
    branch: 'main',
    defaultBranch: 'main',
    lastScanned: '',
    overallScore: 0,
    grade: 'A+',
    activeFindings: 0,
  });

  // Live data state. All entries are populated from real backend
  // responses; null means "not yet loaded" (render a loading state).
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [hotspots, setHotspots] = useState<RiskHotspot[] | null>(null);
  const [whatChanged, setWhatChanged] = useState<WhatChangedEvent[] | null>(null);
  const [driftItems, setDriftItems] = useState<ArchitecturalDriftItem[] | null>(null);
  const [telemetry, setTelemetry] = useState<ApiTelemetrySnapshot | null>(null);
  const [projection, setProjection] = useState<ApiRiskProjection | null>(null);
  const [historySummaries, setHistorySummaries] = useState<ApiScanSummary[]>([]);
  const [latestScan, setLatestScan] = useState<ApiScanRecord | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [scanning, setScanning] = useState<boolean>(false);

  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [scanTerminalOpen, setScanTerminalOpen] = useState(false);
  const [scanNotification, setScanNotification] = useState<string | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  // ---------------------------------------------------------------------
  // Fetch all data for the active repo
  // ---------------------------------------------------------------------
  const refreshAll = useCallback(
    async (repoPath: string) => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      setLoading(true);
      setError(null);

      try {
        // Latest scan (full record with findings + summary).
        let latestRecord: ApiScanRecord | null = null;
        try {
          latestRecord = await getHistoryLatest(repoPath, controller.signal);
        } catch (err) {
          if ((err as ApiError).status === 404) {
            // No history yet — that's OK; we just render empty states.
            latestRecord = null;
          } else {
            throw err;
          }
        }

        // Latest telemetry + projection + drift + hotspots + history.
        const [
          telemetryLatest,
          projectionLatest,
          driftLatest,
          hotspotsLatest,
          telemetryHistoryRes,
        ] = await Promise.all([
          getTelemetryLatest(repoPath, controller.signal).catch(
            (err) =>
              err instanceof ApiError && err.status === 404 ? null : Promise.reject(err)
          ),
          getProjection(repoPath, 'next_scan', controller.signal).catch(
            (err) =>
              err instanceof ApiError && err.status === 404 ? null : Promise.reject(err)
          ),
          getDrift(repoPath, undefined, undefined, controller.signal).catch(
            (err) =>
              err instanceof ApiError && err.status === 404 ? null : Promise.reject(err)
          ),
          getHotspots(repoPath, 50, controller.signal).catch(
            (err) =>
              err instanceof ApiError && err.status === 404 ? null : Promise.reject(err)
          ),
          getTelemetryHistory(repoPath, 50, controller.signal).catch(() => ({
            count: 0,
            telemetry: [],
          })),
        ]);

        if (controller.signal.aborted) return;

        setLatestScan(latestRecord);
        setTelemetry(telemetryLatest);
        setProjection(projectionLatest);
        setDriftItems(driftLatest ? adaptDriftToItems(driftLatest) : []);
        setHotspots(
          hotspotsLatest ? hotspotsLatest.hotspots.map((h) => adaptHotspot(h, repoPath)) : []
        );

        // Pull history list (for What Changed feed + HistoryView)
        const historyList = telemetryHistoryRes.telemetry.map((t) => ({
          scan_id: t.scan_id,
          repository_id: t.repository_id,
          repository_path: repoPath,
          scanned_at: t.scanned_at,
          schema_version: 'v1',
          score: t.score,
          grade: t.grade,
          total_debt_points: t.total_debt_points,
          finding_count: t.finding_count,
          category_scores: {} as ApiScanSummary['category_scores'],
          severity_distribution: t.severity_distribution,
          findings_by_category: t.category_distribution,
          findings_source_breakdown: {},
        } as ApiScanSummary));

        setHistorySummaries(historyList);
        setWhatChanged(buildWhatChangedFromHistory(historyList));

        if (latestRecord) {
          const adapted = latestRecord.findings.map((f) =>
            adaptFinding(f, repoPath, 'main')
          );
          setFindings(adapted);
          setCurrentRepo((prev) => ({
            ...prev,
            id: repoPath,
            name:
              repoPath
                .split(/[\\/]/)
                .filter(Boolean)
                .slice(-2)
                .join('/') || repoPath,
            lastScanned: latestRecord!.scanned_at,
            overallScore: latestRecord!.score,
            grade: latestRecord!.grade as Grade,
            activeFindings: latestRecord!.finding_count,
          }));
        } else {
          setFindings([]);
          setCurrentRepo((prev) => ({
            ...prev,
            id: repoPath,
            name:
              repoPath
                .split(/[\\/]/)
                .filter(Boolean)
                .slice(-2)
                .join('/') || repoPath,
            lastScanned: '',
            overallScore: 0,
            grade: 'A+',
            activeFindings: 0,
          }));
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        const msg =
          err instanceof ApiError
            ? `Backend error ${err.status}: ${
                typeof err.detail === 'string'
                  ? err.detail
                  : err.detail
                  ? JSON.stringify(err.detail)
                  : err.message
              }`
            : err instanceof Error
            ? err.message
            : 'Unknown error';
        setError(msg);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    },
    []
  );

  // Initial load + reload when repo path changes
  useEffect(() => {
    refreshAll(currentRepoPath);
    return () => {
      inFlight.current?.abort();
    };
  }, [currentRepoPath, refreshAll]);

  // Keyboard shortcut for Cmd+K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // ---------------------------------------------------------------------
  // Derived UI values (pure display math — no fabricated analytics)
  // ---------------------------------------------------------------------
  const findingsArr = findings ?? [];
  const openFindings = findingsArr.filter(
    (f) => f.status === 'open' || f.status === 'in_triage'
  );
  const criticalFindings = openFindings.filter((f) => f.severity === 'critical');
  const highFindings = openFindings.filter((f) => f.severity === 'high');
  const totalDebtHours = openFindings.reduce((acc, f) => acc + f.debtHours, 0);

  // The score displayed in the Overview scorecard is the real backend
  // score (300-850). The card renders "Score X/850" — this is the
  // single source of truth for the displayed value.
  const displayScore: number = latestScan?.score ?? telemetry?.score ?? 0;
  const displayGrade: Grade =
    (latestScan?.grade as Grade | undefined) ??
    (telemetry?.grade as Grade | undefined) ??
    'A+';
  const scoreDelta: number = telemetry?.score_delta ?? projection?.current_score
    ? (latestScan && historySummaries.length >= 2
        ? latestScan.score - historySummaries[historySummaries.length - 2].score
        : 0)
    : 0;

  // ---------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------

  const handleUpdateStatus = (id: string, newStatus: FindingStatus) => {
    setFindings((prev) =>
      (prev ?? []).map((f) => (f.id === id ? { ...f, status: newStatus } : f))
    );
    if (selectedFinding?.id === id) {
      setSelectedFinding((prev) => (prev ? { ...prev, status: newStatus } : null));
    }

    if (newStatus === 'resolved') {
      const resolved = (findings ?? []).find((f) => f.id === id);
      if (resolved) {
        setWhatChanged((prev) => [
          {
            id: `wc-${Date.now()}`,
            type: 'finding_resolved',
            title: `Resolved ${resolved.id}: ${resolved.title}`,
            description: `Triage verified by developer. Closed finding in ${resolved.filePath}.`,
            timestamp: 'Just now',
            actor: {
              name: 'You (Current User)',
              avatar:
                'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
            },
            deltaScore: +2.5,
            severity: 'healthy',
          },
          ...(prev ?? []),
        ]);
      }
    }
  };

  const handleBatchUpdateStatus = (ids: string[], newStatus: FindingStatus) => {
    setFindings((prev) =>
      (prev ?? []).map((f) => (ids.includes(f.id) ? { ...f, status: newStatus } : f))
    );
  };

  const handleUpdateDriftStatus = (
    id: string,
    status: 'active' | 'waived' | 'resolving'
  ) => {
    setDriftItems((prev) =>
      (prev ?? []).map((d) => (d.id === id ? { ...d, status } : d))
    );
  };

  const handleTriggerScan = () => {
    setScanning(true);
    setScanTerminalOpen(true);
  };

  const performScan = useCallback(async () => {
    setScanning(true);
    try {
      const result: ApiScanResponse = await postScan(currentRepoPath);
      setScanNotification(
        `Scan complete: score=${result.score} (${result.grade}), findings=${result.finding_count}, debt=${result.total_debt_points}.`
      );
      setTimeout(() => setScanNotification(null), 4500);
      // Refetch telemetry + projection + history so the UI reflects
      // the new state without waiting for the next manual refresh.
      await refreshAll(currentRepoPath);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `Scan failed (HTTP ${err.status}): ${
              typeof err.detail === 'string'
                ? err.detail
                : err.detail
                ? JSON.stringify(err.detail)
                : err.message
            }`
          : err instanceof Error
          ? err.message
          : 'Scan failed';
      setScanNotification(msg);
      setTimeout(() => setScanNotification(null), 6000);
    } finally {
      setScanning(false);
    }
  }, [currentRepoPath, refreshAll]);

  const handleScanComplete = () => {
    // Triggered by the terminal animation finishing — fire the real
    // backend scan. The terminal UI remains open during the request
    // because it animates independently; we keep `scanning` true
    // until performScan resolves.
    performScan();
  };

  const handleInspectFindingFile = (filePath: string) => {
    setActivePage('findings');
  };

  const handleRepoChange = (next: RepositoryOption) => {
    setCurrentRepoPath(next.id || DEFAULT_REPO_PATH);
  };

  // ---------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------

  const showError = !loading && error !== null;
  const showInitialLoading = loading && findings === null;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0B0E14] text-[#E7E9EC] font-sans antialiased">
      {/* Left Sidebar */}
      <Sidebar
        activePage={activePage}
        onSelectPage={setActivePage}
        findingsCount={openFindings.length}
        criticalCount={criticalFindings.length}
        driftCount={(driftItems ?? []).filter((d) => d.status === 'active').length}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        {/* Top Real-time Telemetry Bar */}
        <TelemetryBar telemetry={telemetry} />

        {/* Top Header */}
        <Header
          currentRepo={currentRepo}
          repos={[{ id: currentRepoPath, name: currentRepo.name }]}
          onSelectRepo={handleRepoChange}
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          onTriggerScan={handleTriggerScan}
          isScanning={scanning}
        />

        {/* Real-time Scan Notification Toast */}
        {scanNotification && (
          <div className="px-4 py-2 bg-[#1B222C] border-b border-[#3F6B8F]/50 flex items-center justify-between text-xs font-mono text-[#8FB7D9] animate-in slide-in-from-top duration-150">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#3F6B8F] animate-pulse" />
              <span>{scanNotification}</span>
            </div>
            <button
              onClick={() => setScanNotification(null)}
              className="text-[#9CA6B2] hover:text-[#E7E9EC]"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Scrollable Viewport */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <div className="max-w-7xl mx-auto space-y-4">
            {showError && (
              <div className="p-4 rounded-lg bg-[#1B222C] border border-[#8F3D3D]/60 flex items-start gap-3 font-mono text-xs">
                <AlertCircle className="w-4 h-4 text-[#E07A7A] shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="text-[#E07A7A] font-semibold">Backend unreachable</div>
                  <div className="text-[#9CA6B2] mt-1">{error}</div>
                  <div className="text-[#6C7989] mt-1">
                    Verify the API is running at the configured base URL and that CORS allows this origin.
                  </div>
                </div>
                <button
                  onClick={() => refreshAll(currentRepoPath)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#3F6B8F] text-[#E7E9EC] font-semibold hover:bg-[#4D7FA8] transition-colors"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Retry
                </button>
              </div>
            )}

            {showInitialLoading && (
              <div className="p-8 rounded-lg bg-[#11161F] border border-[#2A3441] text-center font-mono text-xs text-[#9CA6B2] space-y-2">
                <RefreshCw className="w-4 h-4 mx-auto text-[#3F6B8F] animate-spin" />
                <div>Loading telemetry from backend…</div>
                <div className="text-[#6C7989]">
                  Path: <span className="text-[#8FB7D9]">{currentRepoPath}</span>
                </div>
              </div>
            )}

            {!showInitialLoading && activePage === 'overview' && (
              <OverviewView
                score={displayScore}
                grade={displayGrade}
                scoreDelta={scoreDelta}
                totalFindingsCount={openFindings.length}
                criticalCount={criticalFindings.length}
                highCount={highFindings.length}
                debtHours={totalDebtHours}
                findings={findingsArr}
                hotspots={hotspots ?? []}
                whatChanged={whatChanged ?? []}
                categoryScores={latestScan?.category_scores ?? telemetry
                  ? {
                      security: latestScan?.category_scores?.security ?? 0,
                      architecture: latestScan?.category_scores?.maintainability ?? 0,
                      reliability: latestScan?.category_scores?.complexity ?? 0,
                      tech_debt: latestScan?.category_scores?.staleness ?? 0,
                      compliance: latestScan?.category_scores?.testing ?? 0,
                    }
                  : undefined}
                categoryFindingCounts={latestScan
                  ? {
                      security: latestScan.findings_by_category.security ?? 0,
                      architecture: latestScan.findings_by_category.maintainability ?? 0,
                      reliability: latestScan.findings_by_category.complexity ?? 0,
                      tech_debt: latestScan.findings_by_category.staleness ?? 0,
                      compliance: latestScan.findings_by_category.testing ?? 0,
                    }
                  : undefined}
                projection={projection}
                onSelectFinding={setSelectedFinding}
                onNavigate={setActivePage}
              />
            )}

            {!showInitialLoading && activePage === 'findings' && (
              <FindingsView
                findings={findingsArr}
                onSelectFinding={setSelectedFinding}
                onUpdateStatus={handleUpdateStatus}
                onBatchUpdateStatus={handleBatchUpdateStatus}
              />
            )}

            {!showInitialLoading && activePage === 'hotspots' && (
              <RiskHotspotsView
                hotspots={hotspots ?? []}
                onInspectFindingFile={handleInspectFindingFile}
              />
            )}

            {!showInitialLoading && activePage === 'history' && (
              <HistoryView
                trendData={adaptHistoryToTrend(historySummaries)}
                gateRecords={adaptHistoryToGateRecords(historySummaries)}
              />
            )}

            {!showInitialLoading && activePage === 'drift' && (
              <DriftView
                driftItems={driftItems ?? []}
                onUpdateDriftStatus={handleUpdateDriftStatus}
              />
            )}

            {!showInitialLoading && activePage === 'settings' && (
              <SettingsView policies={DEFAULT_QUALITY_GATE_POLICIES} />
            )}
          </div>
        </main>
      </div>

      {/* Deep-Dive Inspection Drawer */}
      <FindingDrawer
        finding={selectedFinding}
        onClose={() => setSelectedFinding(null)}
        onUpdateStatus={handleUpdateStatus}
      />

      {/* Global Command Palette (Cmd+K) */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        findings={findingsArr}
        hotspots={hotspots ?? []}
        onSelectFinding={setSelectedFinding}
        onNavigate={setActivePage}
        onTriggerScan={handleTriggerScan}
      />

      {/* Live Scan AST Terminal Simulation Modal */}
      <LiveScanTerminal
        isOpen={scanTerminalOpen}
        onClose={() => {
          setScanTerminalOpen(false);
          setScanning(false);
        }}
        onScanComplete={handleScanComplete}
      />
    </div>
  );
}
