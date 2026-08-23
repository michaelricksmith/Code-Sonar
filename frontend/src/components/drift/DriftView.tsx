import React, { useState } from 'react';
import {
  GitCompare,
  AlertTriangle,
  ShieldAlert,
  Layers,
  ArrowRight,
  FileCode,
  Network,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Split,
  Plus,
} from 'lucide-react';
import { ArchitecturalDriftItem } from '../../types';
import { SeverityBadge } from '../common/RiskBadge';

interface DriftViewProps {
  driftItems: ArchitecturalDriftItem[];
  onUpdateDriftStatus: (id: string, status: 'active' | 'waived' | 'resolving') => void;
}

export const DriftView: React.FC<DriftViewProps> = ({
  driftItems,
  onUpdateDriftStatus,
}) => {
  const [selectedDrift, setSelectedDrift] = useState<ArchitecturalDriftItem>(driftItems[0]);

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-3 border-b border-[#2A3441]">
        <div>
          <div className="flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-[#3F6B8F]" />
            <h1 className="text-xl font-bold font-mono tracking-tight text-[#E7E9EC]">
              Architectural Drift & Boundary Violations
            </h1>
          </div>
          <p className="text-xs text-[#9CA6B2] font-mono mt-0.5">
            Detect unintended structural decay, prohibited cross-service calls, and layer boundary bypasses against architecture baseline.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-[#151A21] border border-[#2A3441] text-[#E07A7A]">
            {driftItems.filter((d) => d.status === 'active').length} Active Violations
          </span>
        </div>
      </div>

      {/* Grid: Drift List & Diff Inspector */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Drift Violations List (5 cols) */}
        <div className="lg:col-span-5 space-y-3">
          <div className="text-xs font-mono text-[#9CA6B2] px-1">
            Detected Architectural Breaches
          </div>

          <div className="space-y-2.5">
            {driftItems.map((item) => {
              const isSelected = selectedDrift?.id === item.id;

              return (
                <div
                  key={item.id}
                  onClick={() => setSelectedDrift(item)}
                  className={`p-3.5 rounded-lg border transition-all cursor-pointer font-mono text-xs ${
                    isSelected
                      ? 'bg-[#1B222C] border-[#3F6B8F] shadow-lg'
                      : 'bg-[#151A21] border-[#2A3441] hover:border-[#3F6B8F]/60'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1 truncate">
                      <div className="flex items-center gap-2">
                        <SeverityBadge severity={item.severity} size="sm" />
                        <span className="text-[11px] text-[#3F6B8F] uppercase font-bold">
                          {item.type.replace('_', ' ')}
                        </span>
                      </div>
                      <h4 className="font-semibold text-[#E7E9EC] truncate pt-0.5">
                        {item.title}
                      </h4>
                    </div>

                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded capitalize shrink-0 ${
                        item.status === 'active'
                          ? 'bg-[#8F3D3D]/20 text-[#E07A7A] border border-[#8F3D3D]/40'
                          : item.status === 'resolving'
                          ? 'bg-[#C28A3D]/20 text-[#E8B468] border border-[#C28A3D]/40'
                          : 'bg-[#1B222C] text-[#9CA6B2] border border-[#2A3441]'
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>

                  <div className="mt-2.5 pt-2 border-t border-[#2A3441]/70 flex items-center justify-between text-[11px] text-[#6C7989]">
                    <span className="truncate max-w-[200px]">{item.sourceModule.split('/').pop()} → {item.targetModule.split('/').pop()}</span>
                    <span>{new Date(item.detectedAt).toLocaleDateString()}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Deep Diff & Baseline Policy Inspector (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          {selectedDrift && (
            <div className="p-4 rounded-lg bg-[#151A21] border border-[#2A3441] space-y-4 font-mono text-xs">
              <div className="flex items-start justify-between pb-3 border-b border-[#2A3441]">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={selectedDrift.severity} size="sm" />
                    <span className="font-bold text-[#E7E9EC]">{selectedDrift.title}</span>
                  </div>
                  <div className="text-[11px] text-[#9CA6B2]">
                    Introduced in: <span className="text-[#3F6B8F] font-semibold">{selectedDrift.introducedInPR}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() =>
                      onUpdateDriftStatus(
                        selectedDrift.id,
                        selectedDrift.status === 'active' ? 'waived' : 'active'
                      )
                    }
                    className="px-2.5 py-1 rounded bg-[#0E1116] border border-[#2A3441] text-[#9CA6B2] hover:text-[#E7E9EC] text-xs font-mono"
                  >
                    {selectedDrift.status === 'active' ? 'Waive Rule' : 'Reactivate'}
                  </button>
                  <button
                    onClick={() => {
                      alert(`Fix branch created: fix/drift-${selectedDrift.id}`);
                    }}
                    className="px-3 py-1 rounded bg-[#3F6B8F] text-[#E7E9EC] font-semibold hover:bg-[#4D7FA8] text-xs font-mono"
                  >
                    Create Refactor Task
                  </button>
                </div>
              </div>

              {/* Module Flow Graphic */}
              <div className="p-3 rounded-md bg-[#0E1116] border border-[#2A3441] space-y-2">
                <span className="text-[11px] text-[#9CA6B2] uppercase font-bold">Coupling Flow</span>
                <div className="flex items-center gap-3 text-xs">
                  <span className="px-2 py-1 rounded bg-[#1B222C] border border-[#2A3441] text-[#E7E9EC] truncate">
                    {selectedDrift.sourceModule}
                  </span>
                  <ArrowRight className="w-4 h-4 text-[#E07A7A] shrink-0" />
                  <span className="px-2 py-1 rounded bg-[#1B222C] border border-[#8F3D3D]/40 text-[#E07A7A] truncate">
                    {selectedDrift.targetModule}
                  </span>
                </div>
              </div>

              {/* Baseline Rule Description */}
              <div className="space-y-1.5 p-3 rounded-md bg-[#1B222C] border border-[#2A3441]">
                <span className="text-[11px] text-[#8FB7D9] uppercase font-bold">Baseline Architecture Rule</span>
                <p className="text-xs text-[#E7E9EC] font-sans leading-relaxed">
                  {selectedDrift.baselineRule}
                </p>
                <div className="pt-2 text-[11px] text-[#9CA6B2] font-sans border-t border-[#2A3441]/60">
                  {selectedDrift.description}
                </div>
              </div>

              {/* Code Diff (if available) */}
              {selectedDrift.codeDiff && (
                <div className="space-y-2">
                  <div className="text-[11px] text-[#9CA6B2] flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-[#E7E9EC]">
                      <FileCode className="w-3.5 h-3.5 text-[#3F6B8F]" />
                      {selectedDrift.codeDiff.file}
                    </span>
                    <span>Violating AST Delta</span>
                  </div>

                  <div className="rounded-md border border-[#2A3441] bg-[#0E1116] overflow-hidden text-[11px] font-mono leading-relaxed">
                    {selectedDrift.codeDiff.removedLines.map((line, i) => (
                      <div key={i} className="px-3 py-1 bg-[#8F3D3D]/15 text-[#E07A7A] border-l-2 border-[#8F3D3D]">
                        {line}
                      </div>
                    ))}
                    {selectedDrift.codeDiff.addedLines.map((line, i) => (
                      <div key={i} className="px-3 py-1 bg-[#C28A3D]/15 text-[#E8B468] border-l-2 border-[#C28A3D]">
                        {line}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
