import React from 'react';
import {
  TrendingDown,
  TrendingUp,
  AlertTriangle,
  ShieldAlert,
  Flame,
  Layers,
  ArrowRight,
  GitCommit,
  GitPullRequest,
  CheckCircle2,
  Clock,
  ExternalLink,
  ChevronRight,
  Filter,
  BarChart3,
  Activity,
  AlertOctagon,
  FileCode,
  Radio,
  Crosshair,
} from 'lucide-react';
import { Finding, RiskHotspot, WhatChangedEvent, Grade, Category } from '../../types';
import { SeverityBadge, GradeBadge, CategoryBadge } from '../common/RiskBadge';
import { NavPage } from '../common/Sidebar';
import { FuturisticScorecard } from './FuturisticScorecard';
import { SonarRadarHUD } from '../common/SonarRadarHUD';
import { RiskProjectionChart } from './RiskProjectionChart';
import type { ApiRiskProjection } from '../../api/codeSonar';

interface OverviewViewProps {
  score: number;
  grade: Grade;
  scoreDelta: number;
  totalFindingsCount: number;
  criticalCount: number;
  highCount: number;
  debtHours: number;
  findings: Finding[];
  hotspots: RiskHotspot[];
  whatChanged: WhatChangedEvent[];
  /**
   * Per-category scores from the backend (0-100). Keys map the
   * frontend's category taxonomy onto the backend's. When this is
   * undefined the UI falls back to "no data" rows for each
   * category (no fabricated metrics).
   */
  categoryScores?: Record<Category, number>;
  /** Per-category finding counts from the backend. */
  categoryFindingCounts?: Record<Category, number>;
  /** Real projection payload from /api/projection (optional). */
  projection?: ApiRiskProjection | null;
  onSelectFinding: (finding: Finding) => void;
  onNavigate: (page: NavPage) => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  score,
  grade,
  scoreDelta,
  totalFindingsCount,
  criticalCount,
  highCount,
  debtHours,
  findings,
  hotspots,
  whatChanged,
  categoryScores,
  categoryFindingCounts,
  projection,
  onSelectFinding,
  onNavigate,
}) => {
  /**
   * Real per-category rows. Falls back to "no data" when the
   * backend hasn't returned a category breakdown yet — we never
   * fabricate category scores.
   */
  const categoryRows: Array<{ category: Category; score: number | null; count: number }> = [
    { category: 'security', score: categoryScores?.security ?? null, count: categoryFindingCounts?.security ?? 0 },
    { category: 'architecture', score: categoryScores?.architecture ?? null, count: categoryFindingCounts?.architecture ?? 0 },
    { category: 'reliability', score: categoryScores?.reliability ?? null, count: categoryFindingCounts?.reliability ?? 0 },
    { category: 'tech_debt', score: categoryScores?.tech_debt ?? null, count: categoryFindingCounts?.tech_debt ?? 0 },
    { category: 'compliance', score: categoryScores?.compliance ?? null, count: categoryFindingCounts?.compliance ?? 0 },
  ];

  return (
    <div className="space-y-6 pb-12 font-mono">
      {/* Top Banner / Executive Pulse */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-[#222B38]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-[#E7E9EC]">
              Risk Intelligence Command Center
            </h1>
            <span className="text-[11px] px-2 py-0.5 rounded bg-[#151A21] text-[#8FB7D9] border border-[#2A3441]">
              Target: main (HEAD)
            </span>
          </div>
          <p className="text-xs text-[#9CA6B2] mt-1">
            Real-time multi-dimensional telemetry tracking AST vulnerability vectors, topological coupling, and regression risk.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Rule count pill removed: was a fabricated "142" with no backend source. */}
        </div>
      </div>

      {/* Futuristic Scorecard with Circular HUD Dial & What-If Simulator */}
      <FuturisticScorecard
        score={score}
        grade={grade}
        scoreDelta={scoreDelta}
        criticalCount={criticalCount}
        highCount={highCount}
        totalFindings={totalFindingsCount}
        debtHours={debtHours}
      />

      {/* Interactive Sonar Radar Threat HUD */}
      <SonarRadarHUD
        findings={findings}
        hotspots={hotspots}
        onSelectFinding={onSelectFinding}
      />

      {/* 30-Day Risk & Debt Reduction Trend Chart (Recharts) */}
      <RiskProjectionChart
        currentScore={score}
        currentDebtHours={debtHours}
        projection={projection ?? null}
      />

      {/* Main Grid: Left (Risk Breakdown & Priority Findings) | Right (What Changed & Hotspots) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column (2 Cols) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Category Risk Breakdown */}
          <div className="p-4 rounded-xl bg-[#11161F] border border-[#2A3441] space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[#E7E9EC] uppercase tracking-wide">
                  Risk Posture by Domain
                </h3>
                <p className="text-xs text-[#9CA6B2]">
                  AST findings weighted by security severity, architectural boundaries, and runtime reliability.
                </p>
              </div>
              <span className="text-xs text-[#6C7989]">5 Vector Dimensions</span>
            </div>

            <div className="space-y-3">
              {categoryRows.map((row) => {
                const hasData = row.score !== null;
                const percentage = hasData ? Math.max(0, Math.min(100, row.score as number)) : 0;
                return (
                  <div key={row.category} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <CategoryBadge category={row.category} />
                        <span className="text-[11px] text-[#6C7989]">
                          ({row.count} findings)
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`font-semibold ${
                            hasData
                              ? percentage >= 80
                                ? 'text-[#7CC4A8]'
                                : percentage >= 70
                                ? 'text-[#E8B468]'
                                : 'text-[#E07A7A]'
                              : 'text-[#6C7989]'
                          }`}
                        >
                          {hasData ? `Score ${percentage}/100` : 'No data'}
                        </span>
                      </div>
                    </div>

                    {/* Compact custom progress track with glow */}
                    <div className="h-2 w-full rounded-full bg-[#0B0E14] border border-[#222B38] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500 shadow-sm"
                        style={{
                          width: `${percentage}%`,
                          backgroundColor: hasData
                            ? percentage >= 80
                              ? '#4F8A73'
                              : percentage >= 70
                              ? '#C28A3D'
                              : '#8F3D3D'
                            : 'transparent',
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recent Critical & High Priority Findings */}
          <div className="p-4 rounded-xl bg-[#11161F] border border-[#2A3441] space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[#E7E9EC] uppercase tracking-wide">
                  Priority Gating Findings (Requires Triage)
                </h3>
                <p className="text-xs text-[#9CA6B2]">
                  Violations currently triggering CI/CD release gate failure.
                </p>
              </div>
              <button
                onClick={() => onNavigate('findings')}
                className="text-xs text-[#3F6B8F] hover:text-[#8FB7D9] flex items-center gap-1"
              >
                View all ({findings.length}) <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="divide-y divide-[#222B38] border border-[#222B38] rounded-md bg-[#0B0E14] overflow-hidden">
              {findings.slice(0, 5).map((f) => (
                <div
                  key={f.id}
                  onClick={() => onSelectFinding(f)}
                  className="p-3 hover:bg-[#1B222C] cursor-pointer transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3 group"
                >
                  <div className="space-y-1 truncate">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-[#3F6B8F] font-bold">{f.id}</span>
                      <SeverityBadge severity={f.severity} size="sm" />
                      <CategoryBadge category={f.category} />
                      {f.cwe && (
                        <span className="text-[10px] text-[#9CA6B2] bg-[#151A21] px-1 rounded border border-[#2A3441]">
                          {f.cwe}
                        </span>
                      )}
                    </div>
                    <div className="text-xs font-semibold text-[#E7E9EC] truncate group-hover:text-[#8FB7D9] transition-colors">
                      {f.title}
                    </div>
                    <div className="text-[11px] text-[#6C7989] truncate font-mono">
                      {f.filePath}:{f.lineRange[0]} • Introduced by {f.author}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0 self-end sm:self-center text-xs">
                    <div className="text-right">
                      <span className="text-[11px] text-[#9CA6B2] block">Debt Cost</span>
                      <span className="text-[#8FB7D9] font-bold">{f.debtHours}h</span>
                    </div>
                    <ChevronRight className="w-4 h-4 text-[#6C7989] group-hover:text-[#E7E9EC] group-hover:translate-x-0.5 transition-all" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column (1 Col) */}
        <div className="space-y-6">
          {/* "What Changed" Delta Feed */}
          <div className="p-4 rounded-xl bg-[#11161F] border border-[#2A3441] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-[#3F6B8F]" />
                <h3 className="text-sm font-semibold text-[#E7E9EC] uppercase tracking-wide">
                  What Changed (Delta Feed)
                </h3>
              </div>
              <span className="text-[11px] text-[#6C7989]">Latest 24h</span>
            </div>

            <div className="space-y-3">
              {whatChanged.map((event) => (
                <div
                  key={event.id}
                  className="p-2.5 rounded-md bg-[#0B0E14] border border-[#222B38] space-y-1.5 text-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-semibold text-[#E7E9EC] leading-snug">
                      {event.title}
                    </span>
                    <span
                      className={`text-[11px] font-bold shrink-0 ${
                        event.deltaScore > 0
                          ? 'text-[#7CC4A8]'
                          : event.deltaScore < 0
                          ? 'text-[#E07A7A]'
                          : 'text-[#9CA6B2]'
                      }`}
                    >
                      {event.deltaScore > 0 ? `+${event.deltaScore}` : event.deltaScore} pts
                    </span>
                  </div>

                  <p className="text-[11px] text-[#9CA6B2] font-sans leading-relaxed">
                    {event.description}
                  </p>

                  <div className="pt-1 flex items-center justify-between text-[10px] text-[#6C7989] border-t border-[#222B38]">
                    <span className="flex items-center gap-1.5">
                      <img
                        src={event.actor.avatar}
                        alt={event.actor.name}
                        className="w-3.5 h-3.5 rounded-full border border-[#2A3441]"
                      />
                      <span>{event.actor.name}</span>
                    </span>
                    <span>{event.timestamp}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Top Risk Hotspots Summary */}
          <div className="p-4 rounded-xl bg-[#11161F] border border-[#2A3441] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Flame className="w-4 h-4 text-[#B85C4A]" />
                <h3 className="text-sm font-semibold text-[#E7E9EC] uppercase tracking-wide">
                  Top Risk Hotspots
                </h3>
              </div>
              <button
                onClick={() => onNavigate('hotspots')}
                className="text-xs text-[#3F6B8F] hover:text-[#8FB7D9]"
              >
                All Hotspots
              </button>
            </div>

            <p className="text-xs text-[#9CA6B2]">
              Files with high churn frequency combined with high complexity and low test coverage.
            </p>

            <div className="space-y-2">
              {hotspots.slice(0, 3).map((spot) => (
                <div
                  key={spot.id}
                  onClick={() => onNavigate('hotspots')}
                  className="p-2.5 rounded-md bg-[#0B0E14] border border-[#222B38] hover:border-[#3F6B8F] cursor-pointer transition-colors space-y-1.5"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-[#E7E9EC] font-semibold truncate pr-2">
                      {spot.filePath.split('/').pop()}
                    </span>
                    <span className="text-xs font-bold text-[#E07A7A]">
                      Risk {spot.riskScore}/100
                    </span>
                  </div>

                  <div className="text-[10px] text-[#6C7989] truncate">
                    {spot.filePath}
                  </div>

                  <div className="flex items-center justify-between text-[10px] text-[#9CA6B2] pt-1 border-t border-[#222B38]">
                    <span>{spot.commitCount30d} commits (30d)</span>
                    <span className="text-[#E8B468]">Coverage: {spot.testCoverage}%</span>
                    <span className="text-[#8FB7D9]">v(G)={spot.cyclomaticComplexity}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
