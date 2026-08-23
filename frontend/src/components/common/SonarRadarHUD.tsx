import React, { useState, useEffect } from 'react';
import {
  Radio,
  Crosshair,
  ShieldAlert,
  Flame,
  Activity,
  Layers,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Filter,
  Eye,
  Info,
} from 'lucide-react';
import { Finding, RiskHotspot } from '../../types';

interface SonarRadarHUDProps {
  findings: Finding[];
  hotspots: RiskHotspot[];
  onSelectFinding: (finding: Finding) => void;
  onSelectHotspot?: (hotspot: RiskHotspot) => void;
}

export const SonarRadarHUD: React.FC<SonarRadarHUDProps> = ({
  findings,
  hotspots,
  onSelectFinding,
}) => {
  const [hoveredBlip, setHoveredBlip] = useState<{
    id: string;
    title: string;
    type: 'finding' | 'hotspot';
    severity: string;
    score: number;
    module: string;
    x: number;
    y: number;
    rawFinding?: Finding;
  } | null>(null);

  const [activeLayer, setActiveLayer] = useState<'all' | 'critical_only' | 'hotspots'>('all');
  const [radarActive, setRadarActive] = useState(true);
  const [coordinateReadout, setCoordinateReadout] = useState({ azimuth: 142.8, distance: 4.2 });

  // Update synthetic coordinate telemetry
  useEffect(() => {
    const interval = setInterval(() => {
      setCoordinateReadout({
        azimuth: Number((100 + Math.random() * 260).toFixed(1)),
        distance: Number((2.0 + Math.random() * 6.5).toFixed(2)),
      });
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  // Map findings to polar radar coordinates (0 to 100 distance from center)
  // Center = High Risk / Critical (Radius 20-45%), Outer = Low Risk (Radius 70-90%)
  const blips = [
    // Mapped Critical Findings (closer to center)
    ...findings.map((f, i) => {
      const angle = (i * 47.3 + 25) % 360;
      const rad = (angle * Math.PI) / 180;
      const distance =
        f.severity === 'critical' ? 26 + (i * 7) % 20 : f.severity === 'high' ? 52 + (i * 9) % 18 : 78;
      
      const x = 50 + (distance / 2) * Math.cos(rad);
      const y = 50 + (distance / 2) * Math.sin(rad);

      return {
        id: f.id,
        title: f.title,
        type: 'finding' as const,
        severity: f.severity,
        score: f.impactScore,
        module: f.filePath.split('/').pop() || f.filePath,
        x,
        y,
        angle,
        distance,
        rawFinding: f,
      };
    }),
    // Mapped Hotspots
    ...hotspots.map((h, i) => {
      const angle = (i * 83.7 + 140) % 360;
      const rad = (angle * Math.PI) / 180;
      const distance = 35 + (h.riskScore / 100) * 45;
      const x = 50 + (distance / 2) * Math.cos(rad);
      const y = 50 + (distance / 2) * Math.sin(rad);

      return {
        id: h.id,
        title: `Hotspot: ${h.filePath.split('/').pop()} (v(G)=${h.cyclomaticComplexity})`,
        type: 'hotspot' as const,
        severity: h.riskScore >= 80 ? 'critical' : 'high',
        score: h.riskScore,
        module: h.filePath,
        x,
        y,
        angle,
        distance,
      };
    }),
  ];

  const filteredBlips = blips.filter((b) => {
    if (activeLayer === 'critical_only') return b.severity === 'critical';
    if (activeLayer === 'hotspots') return b.type === 'hotspot';
    return true;
  });

  return (
    <div className="p-4 rounded-xl bg-[#11161F] border border-[#2A3441] shadow-2xl relative overflow-hidden font-mono">
      {/* High-tech Top Header with HUD Indicators */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#222B38] relative z-10">
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <Radio className="w-4 h-4 text-[#3F6B8F] animate-pulse" />
            <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-[#3F6B8F] animate-ping opacity-75" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-[#E7E9EC] tracking-wide uppercase">
                Sonar Threat Topological Radar
              </h3>
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40">
                LIVE SWEEP 360°
              </span>
            </div>
            <p className="text-[11px] text-[#9CA6B2]">
              Radial projection of AST vulnerability vectors & high-complexity blast radiuses.
            </p>
          </div>
        </div>

        {/* Telemetry controls */}
        <div className="flex items-center gap-2 self-start sm:self-center text-xs">
          <div className="flex items-center bg-[#0B0E14] border border-[#222B38] rounded-md p-0.5">
            <button
              onClick={() => setActiveLayer('all')}
              className={`px-2 py-1 rounded text-[11px] transition-colors ${
                activeLayer === 'all'
                  ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#3F6B8F]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              All Vectors ({blips.length})
            </button>
            <button
              onClick={() => setActiveLayer('critical_only')}
              className={`px-2 py-1 rounded text-[11px] transition-colors ${
                activeLayer === 'critical_only'
                  ? 'bg-[#8F3D3D]/30 text-[#E07A7A] font-bold border border-[#8F3D3D]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              Critical Ring
            </button>
            <button
              onClick={() => setActiveLayer('hotspots')}
              className={`px-2 py-1 rounded text-[11px] transition-colors ${
                activeLayer === 'hotspots'
                  ? 'bg-[#C28A3D]/30 text-[#E8B468] font-bold border border-[#C28A3D]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              Hotspots
            </button>
          </div>

          <button
            onClick={() => setRadarActive(!radarActive)}
            className={`p-1.5 rounded-md border text-xs transition-colors ${
              radarActive
                ? 'bg-[#3F6B8F]/20 text-[#8FB7D9] border-[#3F6B8F]/50'
                : 'bg-[#0B0E14] text-[#6C7989] border-[#222B38]'
            }`}
            title="Toggle Radar Sweep"
          >
            <Crosshair className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Main Radar Screen Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 mt-4 items-center">
        {/* Radar Circular Scope (7 Cols) */}
        <div className="lg:col-span-7 flex items-center justify-center p-2 relative">
          <div className="w-full max-w-[340px] aspect-square relative flex items-center justify-center rounded-full bg-[#0B0E14] border border-[#2A3441] shadow-[inset_0_0_30px_rgba(0,0,0,0.8)] overflow-hidden">
            {/* Concentric Radar Range Rings */}
            <div className="absolute inset-[10%] rounded-full border border-[#222B38]/80 pointer-events-none" />
            <div className="absolute inset-[25%] rounded-full border border-[#222B38]/70 pointer-events-none" />
            <div className="absolute inset-[40%] rounded-full border border-[#3F6B8F]/30 pointer-events-none" />
            <div className="absolute inset-[58%] rounded-full border border-[#8F3D3D]/30 pointer-events-none border-dashed" />
            <div className="absolute inset-[75%] rounded-full border border-[#8F3D3D]/50 pointer-events-none" />

            {/* Radar Crosshairs */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="w-full h-px bg-[#222B38]/80" />
            </div>
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="h-full w-px bg-[#222B38]/80" />
            </div>
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none rotate-45">
              <div className="w-full h-px bg-[#222B38]/40" />
            </div>
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none -rotate-45">
              <div className="w-full h-px bg-[#222B38]/40" />
            </div>

            {/* Center Sonar Origin Target */}
            <div className="w-3 h-3 rounded-full bg-[#3F6B8F] ring-4 ring-[#3F6B8F]/30 relative z-20 flex items-center justify-center">
              <div className="w-1 h-1 rounded-full bg-white animate-ping" />
            </div>

            {/* Rotating Sonar Radar Beam */}
            {radarActive && (
              <div className="absolute inset-0 pointer-events-none animate-radar-sweep origin-center z-10">
                <div
                  className="w-1/2 h-1/2 absolute top-0 right-0 origin-bottom-left"
                  style={{
                    background:
                      'conic-gradient(from 0deg at 0% 100%, rgba(63, 107, 143, 0.45) 0deg, rgba(63, 107, 143, 0.05) 55deg, transparent 75deg)',
                  }}
                />
                <div className="w-1/2 h-0.5 bg-gradient-to-r from-transparent via-[#8FB7D9] to-white absolute top-1/2 right-0 origin-left shadow-[0_0_8px_#8FB7D9]" />
              </div>
            )}

            {/* Radar Distance Markers */}
            <span className="absolute top-2 left-1/2 -translate-x-1/2 text-[9px] text-[#6C7989]">N 000°</span>
            <span className="absolute bottom-2 left-1/2 -translate-x-1/2 text-[9px] text-[#6C7989]">S 180°</span>
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[9px] text-[#6C7989]">W 270°</span>
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] text-[#6C7989]">E 090°</span>

            <span className="absolute top-[28%] left-[52%] text-[8px] text-[#8F3D3D] font-bold">CRITICAL CORE</span>

            {/* Interactive Threat Blips on Radar */}
            {filteredBlips.map((blip) => {
              const isHovered = hoveredBlip?.id === blip.id;
              const isCritical = blip.severity === 'critical';
              const isHigh = blip.severity === 'high';

              const colorClass = isCritical
                ? 'bg-[#E07A7A] ring-[#8F3D3D] shadow-[#E07A7A]/50'
                : isHigh
                ? 'bg-[#E8B468] ring-[#C28A3D] shadow-[#E8B468]/50'
                : 'bg-[#8FB7D9] ring-[#3F6B8F] shadow-[#8FB7D9]/50';

              return (
                <div
                  key={blip.id}
                  style={{ left: `${blip.x}%`, top: `${blip.y}%` }}
                  onMouseEnter={() => setHoveredBlip(blip)}
                  onClick={() => {
                    if (blip.rawFinding) {
                      onSelectFinding(blip.rawFinding);
                    }
                  }}
                  className={`absolute -translate-x-1/2 -translate-y-1/2 cursor-pointer z-30 transition-transform ${
                    isHovered ? 'scale-150 z-40' : 'hover:scale-125'
                  }`}
                >
                  <div
                    className={`w-2.5 h-2.5 rounded-full ring-2 shadow-sm ${colorClass} ${
                      isCritical ? 'animate-pulse' : ''
                    }`}
                  />
                  {isHovered && (
                    <div className="absolute -top-1 -left-1 w-4.5 h-4.5 rounded-full border border-white animate-ping pointer-events-none" />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Radar Telemetry & Target Vector Inspector (5 Cols) */}
        <div className="lg:col-span-5 space-y-3 bg-[#0B0E14] p-3.5 rounded-lg border border-[#222B38] text-xs">
          <div className="flex items-center justify-between text-[11px] text-[#9CA6B2] pb-2 border-b border-[#222B38]">
            <span className="flex items-center gap-1 text-[#8FB7D9]">
              <Crosshair className="w-3 h-3 text-[#3F6B8F]" />
              RADAR COORDINATE TELEMETRY
            </span>
            <span className="text-[#4F8A73]">LOCK: ACTIVE</span>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="bg-[#11161F] p-2 rounded border border-[#222B38]">
              <span className="text-[#6C7989] block text-[10px]">RADIAL AZIMUTH</span>
              <span className="text-[#E7E9EC] font-bold">{coordinateReadout.azimuth}° NE</span>
            </div>
            <div className="bg-[#11161F] p-2 rounded border border-[#222B38]">
              <span className="text-[#6C7989] block text-[10px]">VECTOR DISTANCE</span>
              <span className="text-[#8FB7D9] font-bold">{coordinateReadout.distance}k AST</span>
            </div>
          </div>

          {/* Inspected Target Card */}
          {hoveredBlip ? (
            <div className="p-2.5 rounded-md bg-[#1B222C] border border-[#3F6B8F]/60 space-y-2 animate-in fade-in duration-100">
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-0.5">
                  <span className="text-[10px] text-[#3F6B8F] uppercase font-bold">
                    [TARGET LOCKED: {hoveredBlip.id}]
                  </span>
                  <div className="font-semibold text-[#E7E9EC] text-xs leading-snug">
                    {hoveredBlip.title}
                  </div>
                </div>
                <span
                  className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                    hoveredBlip.severity === 'critical'
                      ? 'bg-[#8F3D3D]/30 text-[#E07A7A] border border-[#8F3D3D]/50'
                      : 'bg-[#C28A3D]/30 text-[#E8B468] border border-[#C28A3D]/50'
                  }`}
                >
                  {hoveredBlip.severity}
                </span>
              </div>

              <div className="text-[11px] text-[#9CA6B2] flex items-center justify-between pt-1 border-t border-[#2A3441]/80">
                <span className="truncate max-w-[150px]">{hoveredBlip.module}</span>
                <span className="text-[#E07A7A] font-bold">Impact: {hoveredBlip.score}/100</span>
              </div>

              {hoveredBlip.rawFinding && (
                <button
                  onClick={() => onSelectFinding(hoveredBlip.rawFinding!)}
                  className="w-full mt-1 py-1 rounded bg-[#3F6B8F] text-[#E7E9EC] text-[11px] font-semibold hover:bg-[#4D7FA8] transition-colors text-center block"
                >
                  Deep Inspect AST Node →
                </button>
              )}
            </div>
          ) : (
            <div className="p-4 rounded-md bg-[#11161F] border border-dashed border-[#222B38] text-center text-[#6C7989] text-[11px] space-y-1">
              <Crosshair className="w-5 h-5 mx-auto text-[#3F6B8F]/50" />
              <div>Hover any target blip on radar to lock onto AST vulnerability node.</div>
            </div>
          )}

          {/* Quick Legend */}
          <div className="flex items-center justify-between text-[10px] text-[#6C7989] pt-1">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[#E07A7A]" /> Critical Ring (Inner)
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[#E8B468]" /> High Threat
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[#8FB7D9]" /> Warning Edge
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
