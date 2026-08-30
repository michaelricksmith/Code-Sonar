import React, { useState } from 'react';
import {
  History,
  TrendingDown,
  TrendingUp,
  ShieldCheck,
  ShieldAlert,
  GitCommit,
  Calendar,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Filter,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LineChart,
  Line,
} from 'recharts';
import { ReleaseGateRecord } from '../../types';

interface HistoryViewProps {
  /**
   * Per-scan trend data derived from the real backend history
   * (`/api/telemetry/history` or `/api/history/list`).
   */
  trendData: Array<{
    date: string;
    score: number;
    critical: number;
    debtHours: number;
  }>;
  /**
   * Release-gate audit records rendered in the bottom list. Each
   * record corresponds to one scan in the repository's history.
   */
  gateRecords: ReleaseGateRecord[];
}

export const HistoryView: React.FC<HistoryViewProps> = ({
  trendData,
  gateRecords,
}) => {
  const [timeRange, setTimeRange] = useState<'30d' | '90d' | 'all'>('30d');
  const [selectedGate, setSelectedGate] = useState<ReleaseGateRecord | null>(
    gateRecords[0] ?? null
  );

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-3 border-b border-[#2A3441]">
        <div>
          <div className="flex items-center gap-2">
            <History className="w-5 h-5 text-[#3F6B8F]" />
            <h1 className="text-xl font-bold font-mono tracking-tight text-[#E7E9EC]">
              Risk Evolution & Gated Releases
            </h1>
          </div>
          <p className="text-xs text-[#9CA6B2] font-mono mt-0.5">
            Longitudinal trend of codebase risk score, technical debt hours, and CI/CD Quality Gate decisions.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[#9CA6B2]">Timeline:</span>
          {(['30d', '90d', 'all'] as const).map((r) => (
            <button
              key={r}
              onClick={() => setTimeRange(r)}
              className={`px-2.5 py-1 rounded text-xs font-mono uppercase transition-colors ${
                timeRange === r
                  ? 'bg-[#3F6B8F] text-[#E7E9EC] font-bold'
                  : 'bg-[#151A21] text-[#9CA6B2] border border-[#2A3441] hover:text-[#E7E9EC]'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Main Longitudinal Trend Chart */}
      <div className="p-4 rounded-lg bg-[#151A21] border border-[#2A3441] space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold font-mono text-[#E7E9EC]">
              Software Risk Score Trend vs. Tech Debt
            </h3>
            <p className="text-xs text-[#9CA6B2] font-mono">
              Composite score (0-100, higher is safer) plotted against accumulated debt hours.
            </p>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-[#3F6B8F]" />
              <span className="text-[#8FB7D9]">Risk Score (0-100)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-[#8F3D3D]" />
              <span className="text-[#E07A7A]">Critical Findings</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-[#C28A3D] border-dashed" />
              <span className="text-[#E8B468]">Debt Hours</span>
            </div>
          </div>
        </div>

        {/* Recharts Area Container */}
        <div className="h-64 w-full">
          {trendData.length === 0 ? (
            <div className="h-full w-full flex items-center justify-center text-center text-[11px] text-[#6C7989] font-mono">
              <div className="space-y-1">
                <div className="text-[#8FB7D9]">No scan history available</div>
                <div>Trigger a scan to start recording history.</div>
              </div>
            </div>
          ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="scoreGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3F6B8F" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#3F6B8F" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2A3441" vertical={false} />
              <XAxis
                dataKey="date"
                stroke="#6C7989"
                fontSize={11}
                tickLine={false}
                fontFamily="JetBrains Mono"
              />
              <YAxis
                stroke="#6C7989"
                fontSize={11}
                tickLine={false}
                domain={[300, 850]}
                fontFamily="JetBrains Mono"
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (active && payload && payload.length) {
                    return (
                      <div className="bg-[#0E1116] border border-[#2A3441] p-3 rounded shadow-xl font-mono text-xs space-y-1">
                        <div className="text-[#9CA6B2] font-bold border-b border-[#2A3441] pb-1 mb-1">
                          {label}
                        </div>
                        <div className="text-[#8FB7D9]">
                          Risk Score: <span className="font-bold">{payload[0]?.value}/850</span>
                        </div>
                        <div className="text-[#E07A7A]">
                          Critical+Error: <span className="font-bold">{payload[1]?.value}</span>
                        </div>
                        <div className="text-[#E8B468]">
                          Debt Hours: <span className="font-bold">{payload[2]?.value}h</span>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Area
                type="monotone"
                dataKey="score"
                stroke="#3F6B8F"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#scoreGradient)"
              />
              <Line
                type="monotone"
                dataKey="critical"
                stroke="#8F3D3D"
                strokeWidth={2}
                dot={{ fill: '#8F3D3D', r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="debtHours"
                stroke="#C28A3D"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Release Gates History Table */}
      <div className="p-4 rounded-lg bg-[#151A21] border border-[#2A3441] space-y-4 font-mono text-xs">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-[#E7E9EC]">
              CI/CD Quality Gate Audit Log
            </h3>
            <p className="text-xs text-[#9CA6B2]">
              Historical evaluations of build pipelines against configured risk policies.
            </p>
          </div>
          <span className="text-[11px] text-[#6C7989]">Enforcement: Blocking</span>
        </div>

        <div className="divide-y divide-[#2A3441] border border-[#2A3441] rounded-md bg-[#0E1116] overflow-hidden">
          {gateRecords.length === 0 ? (
            <div className="p-8 text-center text-[#9CA6B2] font-mono text-xs">
              No prior gate decisions recorded for this repository.
            </div>
          ) : (
            gateRecords.map((gate) => (
            <div
              key={gate.id}
              onClick={() => setSelectedGate(selectedGate?.id === gate.id ? null : gate)}
              className="p-3.5 hover:bg-[#1B222C] cursor-pointer transition-colors space-y-2"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  {gate.status === 'passed' && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#4F8A73]/20 border border-[#4F8A73]/40 text-[#7CC4A8] font-semibold text-[11px]">
                      <CheckCircle2 className="w-3 h-3" /> Passed
                    </span>
                  )}
                  {gate.status === 'blocked' && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#8F3D3D]/20 border border-[#8F3D3D]/40 text-[#E07A7A] font-semibold text-[11px]">
                      <XCircle className="w-3 h-3" /> Blocked
                    </span>
                  )}
                  {gate.status === 'overridden' && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#C28A3D]/20 border border-[#C28A3D]/40 text-[#E8B468] font-semibold text-[11px]">
                      <AlertTriangle className="w-3 h-3" /> Overridden
                    </span>
                  )}

                  <span className="font-bold text-[#E7E9EC]">{gate.releaseTag}</span>
                  <span className="text-[11px] text-[#6C7989]">({gate.environment})</span>
                </div>

                <div className="flex items-center gap-4 text-xs text-[#9CA6B2]">
                  <span>Score: <strong className="text-[#E7E9EC]">{gate.riskScore}/850</strong></span>
                  <span>Commit: <strong className="text-[#3F6B8F]">{gate.commitHash}</strong></span>
                  <span>{new Date(gate.timestamp).toLocaleDateString()}</span>
                  <ChevronDown className={`w-4 h-4 text-[#6C7989] transition-transform ${selectedGate?.id === gate.id ? 'rotate-180' : ''}`} />
                </div>
              </div>

              {/* Expanded Rule Audit Details */}
              {selectedGate?.id === gate.id && (
                <div className="pt-3 mt-2 border-t border-[#2A3441] space-y-2 text-[11px] bg-[#151A21] p-3 rounded">
                  <div className="font-semibold text-[#E7E9EC] mb-1">Evaluated Gate Rules:</div>
                  <div className="space-y-1.5">
                    {gate.evaluatedRules.map((r, i) => (
                      <div key={i} className="flex items-center justify-between text-[#9CA6B2]">
                        <span className="flex items-center gap-2">
                          {r.passed ? (
                            <CheckCircle2 className="w-3 h-3 text-[#4F8A73]" />
                          ) : (
                            <XCircle className="w-3 h-3 text-[#8F3D3D]" />
                          )}
                          <span className={r.passed ? 'text-[#E7E9EC]' : 'text-[#E07A7A]'}>{r.rule}</span>
                        </span>
                        <span>
                          Actual: <strong className="text-[#E7E9EC]">{r.actualValue}</strong> (Threshold: {r.threshold})
                        </span>
                      </div>
                    ))}
                  </div>

                  {gate.overriddenBy && (
                    <div className="mt-2 p-2 rounded bg-[#C28A3D]/10 border border-[#C28A3D]/30 text-[#E8B468]">
                      <strong>Manual Override:</strong> {gate.overriddenBy} — "{gate.overrideReason}"
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
          )}
        </div>
      </div>
    </div>
  );
};
