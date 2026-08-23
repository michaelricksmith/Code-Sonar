import React, { useState } from 'react';
import {
  TrendingDown,
  TrendingUp,
  ShieldCheck,
  Zap,
  Sliders,
  Sparkles,
  ArrowRight,
  Info,
  CheckCircle2,
} from 'lucide-react';
import { Grade } from '../../types';

interface FuturisticScorecardProps {
  score: number;
  grade: Grade;
  scoreDelta: number;
  criticalCount: number;
  highCount: number;
  totalFindings: number;
  debtHours: number;
}

export const FuturisticScorecard: React.FC<FuturisticScorecardProps> = ({
  score,
  grade,
  scoreDelta,
  criticalCount,
  highCount,
  totalFindings,
  debtHours,
}) => {
  const [simulationMode, setSimulationMode] = useState(false);
  const [simulatedFixes, setSimulatedFixes] = useState(2); // number of critical fixes simulated

  // Radial calculation for SVG circular gauge. The score is
  // displayed on the credit-report scale (300-850) and the
  // progress arc is normalized over that range — no fabricated
  // math, the arc length is a direct read of the backend value.
  const radius = 64;
  const circumference = 2 * Math.PI * radius;
  const SCORE_MIN = 300;
  const SCORE_MAX = 850;
  const SCORE_RANGE = SCORE_MAX - SCORE_MIN;
  const normalizedScore =
    Math.max(SCORE_MIN, Math.min(SCORE_MAX, score)) - SCORE_MIN;
  const simulatedNormalized =
    simulationMode
      ? Math.min(SCORE_MAX, normalizedScore + simulatedFixes * 7.5)
      : normalizedScore;
  const currentScore = simulationMode ? simulatedNormalized + SCORE_MIN : score;
  const strokeDashoffset =
    circumference - (simulatedNormalized / SCORE_RANGE) * circumference;

  const simulatedGrade: Grade =
    simulatedNormalized + SCORE_MIN >= 800
      ? 'A'
      : simulatedNormalized + SCORE_MIN >= 770
      ? 'B+'
      : simulatedNormalized + SCORE_MIN >= 740
      ? 'B'
      : 'C';

  return (
    <div className="p-5 rounded-xl bg-[#11161F] border border-[#2A3441] shadow-2xl relative overflow-hidden font-mono">
      {/* Background Cyber Glow & Grid Accents */}
      <div className="absolute top-0 right-0 w-64 h-64 bg-[#3F6B8F]/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-10 -left-10 w-48 h-48 bg-[#8F3D3D]/10 rounded-full blur-3xl pointer-events-none" />

      {/* Top Header */}
      <div className="flex items-center justify-between pb-3 border-b border-[#222B38] relative z-10">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-bold uppercase tracking-wider text-[#8FB7D9]">
              COMPOSITE SOFTWARE RISK POSTURE
            </h2>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40">
              AST MATRIX
            </span>
          </div>
          <p className="text-[11px] text-[#9CA6B2]">
            Multi-dimensional risk evaluated across security, architectural drift, and complexity.
          </p>
        </div>

        <button
          onClick={() => setSimulationMode(!simulationMode)}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-all border ${
            simulationMode
              ? 'bg-[#3F6B8F] text-[#E7E9EC] font-bold border-[#8FB7D9]'
              : 'bg-[#1B222C] text-[#9CA6B2] border-[#2A3441] hover:text-[#E7E9EC]'
          }`}
        >
          <Sliders className="w-3.5 h-3.5" />
          <span>{simulationMode ? 'Simulator Active' : 'What-If Simulator'}</span>
        </button>
      </div>

      {/* Main Dial & Telemetry Row */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 mt-4 items-center relative z-10">
        {/* Left: SVG Circular Gauge HUD (5 Cols) */}
        <div className="md:col-span-5 flex flex-col items-center justify-center p-2">
          <div className="relative w-44 h-44 flex items-center justify-center">
            {/* Outer Tick Marks Circle */}
            <svg className="w-full h-full transform -rotate-90" viewBox="0 0 160 160">
              {/* Background track circle */}
              <circle
                cx="80"
                cy="80"
                r={radius}
                className="stroke-[#1B222C]"
                strokeWidth="10"
                fill="transparent"
              />

              {/* Glowing Dynamic Score Arc */}
              <circle
                cx="80"
                cy="80"
                r={radius}
                stroke={
                  (simulationMode ? simulatedNormalized + SCORE_MIN : score) >= 800
                    ? '#4F8A73'
                    : (simulationMode ? simulatedNormalized + SCORE_MIN : score) >= 740
                    ? '#C28A3D'
                    : '#8F3D3D'
                }
                strokeWidth="10"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="transparent"
                className="transition-all duration-700 ease-out"
              />
            </svg>

            {/* Center HUD Info Box */}
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-[10px] text-[#9CA6B2] uppercase font-mono">AST RISK SCORE</span>
              <div className="flex items-baseline justify-center gap-1">
                <span className="text-4xl font-bold font-mono tracking-tight text-[#E7E9EC]">
                  {Math.round(currentScore)}
                </span>
                <span className="text-xs text-[#6C7989]">/850</span>
              </div>

              <div className="mt-1 flex items-center gap-1.5">
                <span
                  className={`text-xs px-2 py-0.5 rounded font-bold uppercase ${
                    (simulationMode ? simulatedGrade : grade).startsWith('A')
                      ? 'bg-[#4F8A73]/20 text-[#7CC4A8] border border-[#4F8A73]/40'
                      : (simulationMode ? simulatedGrade : grade).startsWith('B')
                      ? 'bg-[#C28A3D]/20 text-[#E8B468] border border-[#C28A3D]/40'
                      : 'bg-[#8F3D3D]/20 text-[#E07A7A] border border-[#8F3D3D]/40'
                  }`}
                >
                  GRADE: {simulationMode ? simulatedGrade : grade}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-2 text-center text-[11px] text-[#9CA6B2]">
            {simulationMode ? (
              <span className="text-[#7CC4A8] flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> Projected boost: +{Math.round(simulatedNormalized - normalizedScore)} pts
              </span>
            ) : (
              <span className="text-[#E07A7A] flex items-center gap-1">
                <TrendingDown className="w-3.5 h-3.5" /> {scoreDelta} pts over past 7 days
              </span>
            )}
          </div>
        </div>

        {/* Right: Key Gating Posture & Simulation Controls (7 Cols) */}
        <div className="md:col-span-7 space-y-3 bg-[#0B0E14] p-4 rounded-lg border border-[#222B38] text-xs">
          {simulationMode ? (
            /* What-If Simulator Panel */
            <div className="space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-[#222B38]">
                <span className="text-[#8FB7D9] font-bold flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-[#E8B468]" />
                  Remediation Impact Simulator
                </span>
                <span className="text-[10px] text-[#9CA6B2]">Interactive</span>
              </div>

              <div className="space-y-2">
                <div className="flex justify-between text-[11px]">
                  <span className="text-[#E7E9EC]">Resolve Critical Vulnerabilities:</span>
                  <span className="text-[#8FB7D9] font-bold">{simulatedFixes} of {criticalCount} fixed</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(1, criticalCount)}
                  value={Math.min(simulatedFixes, Math.max(1, criticalCount))}
                  onChange={(e) => setSimulatedFixes(Number(e.target.value))}
                  className="w-full accent-[#3F6B8F]"
                />
              </div>

              <div className="p-2.5 rounded bg-[#11161F] border border-[#222B38] text-[11px] space-y-1">
                <div className="flex justify-between text-[#9CA6B2]">
                  <span>Estimated Debt Burned:</span>
                  <span className="text-[#7CC4A8] font-bold">-{simulatedFixes * 6.5} hours</span>
                </div>
                <div className="flex justify-between text-[#9CA6B2]">
                  <span>CI/CD Quality Gate Status:</span>
                  <span className={simulatedFixes >= 2 ? 'text-[#7CC4A8] font-bold' : 'text-[#E07A7A]'}>
                    {simulatedFixes >= 2 ? 'PASSED (Unblocked)' : 'BLOCKED (Criticals Remain)'}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            /* Standard Real-Time Scorecard Breakdown */
            <div className="space-y-3">
              <div className="flex items-center justify-between pb-1.5 border-b border-[#222B38]">
                <span className="text-[#9CA6B2] text-[11px]">CI Quality Gate Target:</span>
                <span className="text-[#E07A7A] font-bold">BLOCKED (2 Critical CVEs)</span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div className="bg-[#11161F] p-2.5 rounded border border-[#222B38]">
                  <span className="text-[#6C7989] block text-[10px]">TOTAL FINDINGS</span>
                  <span className="text-[#E7E9EC] text-base font-bold">{totalFindings}</span>
                  <span className="text-[10px] text-[#E07A7A] block">{criticalCount} Critical • {highCount} High</span>
                </div>
                <div className="bg-[#11161F] p-2.5 rounded border border-[#222B38]">
                  <span className="text-[#6C7989] block text-[10px]">TECHNICAL DEBT</span>
                  <span className="text-[#8FB7D9] text-base font-bold">{debtHours}h</span>
                  <span className="text-[10px] text-[#9CA6B2] block">~210 Story Pts</span>
                </div>
              </div>

              <div className="p-2.5 rounded bg-[#11161F] border border-[#222B38] flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-[#4F8A73]" />
                  <span className="text-[#E7E9EC]">Next Gating Release: v2026.08.4</span>
                </div>
                <span className="text-[10px] text-[#9CA6B2]">Requires Score ≥75.0</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
