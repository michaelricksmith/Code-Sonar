import React, { useEffect, useState } from 'react';
import {
  Activity,
  Cpu,
  Radio,
  Shield,
  Layers,
  Database,
  Lock,
  Zap,
} from 'lucide-react';
import type { ApiTelemetrySnapshot } from '../../api/codeSonar';

interface TelemetryBarProps {
  telemetry: ApiTelemetrySnapshot | null;
}

/**
 * Real-time telemetry strip displayed at the top of the app shell.
 *
 * When a `telemetry` snapshot is available, the bar shows real
 * values from `/api/telemetry/latest` (scan duration, analyzer
 * counts, risk velocity, etc.). When the backend is loading or
 * unreachable, it falls back to a small set of derived placeholder
 * strings — but NEVER to fabricated random metrics.
 *
 * The bar keeps the original visual structure (icon + label +
 * value) and palette exactly; only the source of the numbers
 * changes from a `setInterval` random-walk to real API data.
 */
export const TelemetryBar: React.FC<TelemetryBarProps> = ({ telemetry }) => {
  // Live values are still kept in state so the bar can show
  // changes between backend snapshots, but they only update from
  // real telemetry values — never from Math.random().
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 3000);
    return () => clearInterval(interval);
  }, []);

  const astNodes = telemetry?.files_analyzed
    ? telemetry.files_analyzed.toLocaleString()
    : '—';

  const parserLatency =
    typeof telemetry?.scan_duration_ms === 'number'
      ? `${Math.round(telemetry.scan_duration_ms)}ms`
      : '—';

  const evalRulesTotal =
    typeof telemetry?.analyzers_total === 'number'
      ? telemetry.analyzers_total
      : 0;
  const evalRulesSuccessful =
    typeof telemetry?.analyzers_successful === 'number'
      ? telemetry.analyzers_successful
      : 0;

  // Threat block count is approximated as the count of critical
  // + error findings in the latest severity distribution. This is
  // a direct read of the backend payload, not a fabricated metric.
  const threatBlocks =
    (telemetry?.severity_distribution?.critical ?? 0) +
    (telemetry?.severity_distribution?.error ?? 0);

  const scanFrequency =
    typeof telemetry?.scan_frequency_per_day === 'number' &&
    telemetry.scan_frequency_per_day > 0
      ? `${telemetry.scan_frequency_per_day.toFixed(2)}/day`
      : '—';

  return (
    <div
      data-tick={tick}
      className="h-7 bg-[#0B0E14] border-b border-[#222B38] px-4 flex items-center justify-between text-[10px] font-mono text-[#6C7989] select-none shrink-0 overflow-x-auto"
    >
      <div className="flex items-center gap-4 shrink-0">
        <div className="flex items-center gap-1.5 text-[#8FB7D9]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#4F8A73] animate-pulse" />
          <span className="font-bold">SONAR ENGINE: {telemetry ? 'ONLINE' : 'BOOTING'}</span>
        </div>

        <div className="flex items-center gap-1">
          <Cpu className="w-3 h-3 text-[#3F6B8F]" />
          <span>FILES_ANALYZED:</span>
          <span className="text-[#E7E9EC]">{astNodes}</span>
        </div>

        <div className="flex items-center gap-1">
          <Activity className="w-3 h-3 text-[#3F6B8F]" />
          <span>SCAN_MS:</span>
          <span className="text-[#E7E9EC]">{parserLatency}</span>
        </div>

        <div className="hidden sm:flex items-center gap-1">
          <Database className="w-3 h-3 text-[#3F6B8F]" />
          <span>RISK_VEL:</span>
          <span className="text-[#E7E9EC]">
            {typeof telemetry?.risk_velocity_score === 'number'
              ? `${telemetry.risk_velocity_score.toFixed(2)}/scan`
              : '—'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4 shrink-0">
        <div className="hidden md:flex items-center gap-1">
          <Layers className="w-3 h-3 text-[#3F6B8F]" />
          <span>RULES_EVAL:</span>
          <span className="text-[#4F8A73] font-bold">
            {evalRulesSuccessful}/{evalRulesTotal} ACTIVE
          </span>
        </div>

        <div className="flex items-center gap-1 text-[#E07A7A]">
          <Lock className="w-3 h-3" />
          <span>CI_GATE:</span>
          <span className="font-bold">{threatBlocks} BLOCKS</span>
        </div>

        <div className="flex items-center gap-1 text-[#8FB7D9]">
          <span>FREQ:</span>
          <span>{scanFrequency}</span>
        </div>
      </div>
    </div>
  );
};
