import React, { useState } from 'react';
import {
  Flame,
  Activity,
  Layers,
  AlertTriangle,
  GitCommit,
  Users,
  ShieldAlert,
  Code2,
  FileCode,
  Sparkles,
  ArrowRight,
  TrendingUp,
  Percent,
  CheckCircle2,
  Grid,
  List,
  Crosshair,
} from 'lucide-react';
import { RiskHotspot } from '../../types';

interface RiskHotspotsViewProps {
  hotspots: RiskHotspot[];
  onInspectFindingFile: (filePath: string) => void;
}

export const RiskHotspotsView: React.FC<RiskHotspotsViewProps> = ({
  hotspots,
  onInspectFindingFile,
}) => {
  const [selectedHotspot, setSelectedHotspot] = useState<RiskHotspot>(hotspots[0]);
  const [filterRoi, setFilterRoi] = useState<'all' | 'immediate' | 'high' | 'medium'>('all');
  const [viewMode, setViewMode] = useState<'matrix' | 'list'>('matrix');

  const filteredHotspots = hotspots.filter(
    (h) => filterRoi === 'all' || h.refactorRoi === filterRoi
  );

  return (
    <div className="space-y-6 pb-12 font-mono">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-3 border-b border-[#2A3441]">
        <div>
          <div className="flex items-center gap-2">
            <Flame className="w-5 h-5 text-[#B85C4A]" />
            <h1 className="text-xl font-bold tracking-tight text-[#E7E9EC]">
              Risk Hotspots & Complexity Density Matrix
            </h1>
          </div>
          <p className="text-xs text-[#9CA6B2] mt-0.5">
            Pinpoint the high-churn, high-complexity files responsible for 80% of production regression risks.
          </p>
        </div>

        {/* View Switcher & Filters */}
        <div className="flex items-center gap-3">
          {/* Mode Switcher */}
          <div className="flex items-center bg-[#0B0E14] border border-[#2A3441] rounded-md p-0.5 text-xs">
            <button
              onClick={() => setViewMode('matrix')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-colors ${
                viewMode === 'matrix'
                  ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#3F6B8F]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              <Grid className="w-3.5 h-3.5" />
              <span>2D Matrix</span>
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-colors ${
                viewMode === 'list'
                  ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#3F6B8F]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              <List className="w-3.5 h-3.5" />
              <span>List View</span>
            </button>
          </div>

          <div className="h-4 w-px bg-[#2A3441]" />

          {/* ROI Filter */}
          <div className="flex items-center gap-1.5 text-xs">
            {(['all', 'immediate', 'high', 'medium'] as const).map((roi) => (
              <button
                key={roi}
                onClick={() => setFilterRoi(roi)}
                className={`px-2.5 py-1 rounded text-xs capitalize transition-colors ${
                  filterRoi === roi
                    ? 'bg-[#3F6B8F] text-[#E7E9EC] font-bold'
                    : 'bg-[#151A21] text-[#9CA6B2] border border-[#2A3441] hover:text-[#E7E9EC]'
                }`}
              >
                {roi}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 2D Matrix Scatter Plot HUD (Visible in Matrix Mode) */}
      {viewMode === 'matrix' && (
        <div className="p-4 rounded-xl bg-[#11161F] border border-[#2A3441] shadow-2xl space-y-3">
          <div className="flex items-center justify-between text-xs pb-2 border-b border-[#222B38]">
            <span className="text-[#8FB7D9] flex items-center gap-1.5 font-bold">
              <Crosshair className="w-3.5 h-3.5 text-[#3F6B8F]" />
              2D TOPOLOGICAL RISK DENSITY SCATTER (CHURN vs COMPLEXITY)
            </span>
            <span className="text-[#9CA6B2] text-[11px]">
              Bubble size represents failure blast radius
            </span>
          </div>

          {/* Scatter Chart Canvas Area */}
          <div className="relative h-72 w-full bg-[#0B0E14] rounded-lg border border-[#222B38] p-6 overflow-hidden select-none">
            {/* Grid Lines */}
            <div className="absolute inset-0 grid grid-cols-4 grid-rows-4 pointer-events-none opacity-20">
              {Array.from({ length: 16 }).map((_, i) => (
                <div key={i} className="border-r border-b border-[#3F6B8F]" />
              ))}
            </div>

            {/* Axis Labels */}
            <div className="absolute bottom-1 right-4 text-[10px] text-[#6C7989]">
              30-Day Commit Churn Frequency →
            </div>
            <div className="absolute top-2 left-2 text-[10px] text-[#6C7989] -rotate-90 origin-top-left">
              Cyclomatic Complexity v(G) →
            </div>

            {/* High-Risk Danger Zone Quadrant Overlay */}
            <div className="absolute top-0 right-0 w-1/2 h-1/2 bg-[#8F3D3D]/10 border-l border-b border-[#8F3D3D]/30 flex items-start justify-end p-2 pointer-events-none">
              <span className="text-[9px] text-[#E07A7A] font-bold">CRITICAL DANGER ZONE (HIGH CHURN + COMPLEX)</span>
            </div>

            {/* Hotspot Scatter Nodes */}
            {filteredHotspots.map((spot) => {
              // Normalize coordinates: X = Churn (10 to 60 commits), Y = Complexity (10 to 50 v(G))
              const leftPercent = Math.min(90, Math.max(10, ((spot.commitCount30d - 5) / 50) * 85));
              const topPercent = Math.min(85, Math.max(15, 100 - ((spot.cyclomaticComplexity - 5) / 45) * 85));
              const isSelected = selectedHotspot.id === spot.id;

              return (
                <div
                  key={spot.id}
                  onClick={() => setSelectedHotspot(spot)}
                  style={{ left: `${leftPercent}%`, top: `${topPercent}%` }}
                  className="absolute -translate-x-1/2 -translate-y-1/2 cursor-pointer z-20 group"
                >
                  <div
                    className={`rounded-full transition-all duration-200 flex items-center justify-center font-bold text-[9px] ${
                      spot.riskScore >= 85
                        ? 'w-10 h-10 bg-[#8F3D3D]/40 border-2 border-[#E07A7A] text-[#E07A7A] shadow-[0_0_12px_rgba(224,122,122,0.4)]'
                        : spot.riskScore >= 75
                        ? 'w-8 h-8 bg-[#C28A3D]/40 border-2 border-[#E8B468] text-[#E8B468]'
                        : 'w-7 h-7 bg-[#3F6B8F]/40 border-2 border-[#8FB7D9] text-[#8FB7D9]'
                    } ${isSelected ? 'ring-4 ring-white scale-125 z-30' : 'hover:scale-115'}`}
                  >
                    {spot.riskScore}
                  </div>

                  {/* Tooltip on hover */}
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block bg-[#1B222C] border border-[#2A3441] rounded px-2 py-1 text-[10px] text-[#E7E9EC] whitespace-nowrap shadow-xl z-40">
                    <span className="font-bold block">{spot.filePath.split('/').pop()}</span>
                    <span className="text-[#9CA6B2]">
                      Churn: {spot.commitCount30d}c • v(G)={spot.cyclomaticComplexity}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Main Grid: Hotspot List & Deep Inspector */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Hotspot List (2 Cols) */}
        <div className="lg:col-span-2 space-y-3">
          <div className="flex items-center justify-between text-xs text-[#9CA6B2] px-1">
            <span>Ranked by Composite Risk Index (Churn × Complexity / Test Coverage)</span>
            <span>{filteredHotspots.length} files detected</span>
          </div>

          <div className="space-y-2.5">
            {filteredHotspots.map((spot, index) => {
              const isSelected = selectedHotspot.id === spot.id;

              return (
                <div
                  key={spot.id}
                  onClick={() => setSelectedHotspot(spot)}
                  className={`p-3.5 rounded-lg border transition-all cursor-pointer text-xs ${
                    isSelected
                      ? 'bg-[#1B222C] border-[#3F6B8F] shadow-lg'
                      : 'bg-[#151A21] border-[#2A3441] hover:border-[#3F6B8F]/60'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1 truncate">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-[#3F6B8F]">#{index + 1}</span>
                        <span className="font-semibold text-[#E7E9EC] truncate">
                          {spot.filePath.split('/').pop()}
                        </span>
                        <span
                          className={`text-[10px] px-1.5 py-0.2 rounded uppercase font-bold ${
                            spot.refactorRoi === 'immediate'
                              ? 'bg-[#8F3D3D]/20 text-[#E07A7A] border border-[#8F3D3D]/40'
                              : spot.refactorRoi === 'high'
                              ? 'bg-[#C28A3D]/20 text-[#E8B468] border border-[#C28A3D]/40'
                              : 'bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40'
                          }`}
                        >
                          {spot.refactorRoi} ROI
                        </span>
                      </div>

                      <div className="text-[11px] text-[#6C7989] truncate">
                        {spot.filePath}
                      </div>
                      <div className="text-[11px] text-[#9CA6B2] font-sans">
                        Role: {spot.architecturalRole}
                      </div>
                    </div>

                    <div className="text-right shrink-0">
                      <div className="text-lg font-bold text-[#E07A7A]">
                        {spot.riskScore} <span className="text-xs text-[#9CA6B2]">/ 100</span>
                      </div>
                      <span className="text-[10px] text-[#6C7989]">Risk Score</span>
                    </div>
                  </div>

                  {/* Hotspot Metrics Grid */}
                  <div className="grid grid-cols-4 gap-2 pt-3 mt-3 border-t border-[#2A3441]/70 text-[11px]">
                    <div className="flex items-center gap-1.5 text-[#9CA6B2]">
                      <GitCommit className="w-3.5 h-3.5 text-[#3F6B8F]" />
                      <span>{spot.commitCount30d} commits (30d)</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#9CA6B2]">
                      <Users className="w-3.5 h-3.5 text-[#3F6B8F]" />
                      <span>{spot.authorsCount} authors</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#E8B468]">
                      <Activity className="w-3.5 h-3.5" />
                      <span>Complexity v(G)={spot.cyclomaticComplexity}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#8FB7D9]">
                      <Percent className="w-3.5 h-3.5" />
                      <span>Coverage: {spot.testCoverage}%</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Selected Hotspot Deep Dive */}
        <div className="space-y-4">
          <div className="p-4 rounded-lg bg-[#151A21] border border-[#2A3441] space-y-4 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-[#2A3441]">
              <h3 className="text-sm font-semibold text-[#E7E9EC] flex items-center gap-2">
                <FileCode className="w-4 h-4 text-[#3F6B8F]" />
                Hotspot Inspector
              </h3>
              <span className="text-xs font-bold text-[#E07A7A]">
                Score {selectedHotspot.riskScore}/100
              </span>
            </div>

            <div className="space-y-1">
              <div className="text-[11px] text-[#9CA6B2] uppercase">Target Module</div>
              <div className="font-semibold text-[#E7E9EC] break-all bg-[#0E1116] p-2 rounded border border-[#2A3441]">
                {selectedHotspot.filePath}
              </div>
            </div>

            {/* Radar / Dimensions breakdown */}
            <div className="space-y-2.5">
              <div className="text-[11px] text-[#9CA6B2] uppercase">Risk Breakdown Dimensions</div>

              <div className="space-y-1">
                <div className="flex justify-between text-[11px]">
                  <span className="text-[#9CA6B2]">Churn Frequency (30d)</span>
                  <span className="text-[#E07A7A] font-bold">Very High ({selectedHotspot.commitCount30d} commits)</span>
                </div>
                <div className="h-1.5 bg-[#0E1116] rounded-full overflow-hidden">
                  <div className="h-full bg-[#B85C4A]" style={{ width: '88%' }} />
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-[11px]">
                  <span className="text-[#9CA6B2]">Cyclomatic Complexity</span>
                  <span className="text-[#E8B468] font-bold">{selectedHotspot.cyclomaticComplexity} (High nesting)</span>
                </div>
                <div className="h-1.5 bg-[#0E1116] rounded-full overflow-hidden">
                  <div className="h-full bg-[#C28A3D]" style={{ width: '74%' }} />
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-[11px]">
                  <span className="text-[#9CA6B2]">Test Coverage Gap</span>
                  <span className="text-[#E07A7A] font-bold">{100 - selectedHotspot.testCoverage}% unprotected</span>
                </div>
                <div className="h-1.5 bg-[#0E1116] rounded-full overflow-hidden">
                  <div className="h-full bg-[#8F3D3D]" style={{ width: `${100 - selectedHotspot.testCoverage}%` }} />
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-[11px]">
                  <span className="text-[#9CA6B2]">Blast Radius on Failure</span>
                  <span className="text-[#8FB7D9] font-bold">{selectedHotspot.blastRadiusScore}/100</span>
                </div>
                <div className="h-1.5 bg-[#0E1116] rounded-full overflow-hidden">
                  <div className="h-full bg-[#3F6B8F]" style={{ width: `${selectedHotspot.blastRadiusScore}%` }} />
                </div>
              </div>
            </div>

            {/* Active findings on this file */}
            <div className="p-3 rounded-md bg-[#0E1116] border border-[#2A3441] space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-[#9CA6B2]">Active AST Findings</span>
                <span className="text-xs font-bold text-[#E7E9EC]">
                  {selectedHotspot.findingsCount.critical + selectedHotspot.findingsCount.high + selectedHotspot.findingsCount.warning} Total
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#8F3D3D]/20 text-[#E07A7A] border border-[#8F3D3D]/40">
                  {selectedHotspot.findingsCount.critical} Critical
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#B85C4A]/20 text-[#E58D7C] border border-[#B85C4A]/40">
                  {selectedHotspot.findingsCount.high} High
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#C28A3D]/20 text-[#E8B468] border border-[#C28A3D]/40">
                  {selectedHotspot.findingsCount.warning} Warning
                </span>
              </div>
            </div>

            {/* Refactor Action */}
            <button
              onClick={() => onInspectFindingFile(selectedHotspot.filePath)}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-[#3F6B8F] text-[#E7E9EC] font-semibold hover:bg-[#4D7FA8] transition-colors"
            >
              <span>View Findings in this File</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
