import React, { useState } from 'react';
import {
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import {
  TrendingDown,
  TrendingUp,
  Activity,
  Calendar,
  Layers,
  ShieldCheck,
  Target,
  Sparkles,
  HelpCircle,
  Clock,
  ArrowDownRight,
  ArrowUpRight,
} from 'lucide-react';
import type { ApiRiskProjection } from '../../api/codeSonar';

interface TrendDataPoint {
  date: string;
  score: number;
  critical: number;
  high: number;
  debtHours: number;
  commits: number;
  driftCount: number;
  forecast?: number;
  lowerBound?: number;
  upperBound?: number;
  milestone?: string;
}

interface RiskProjectionChartProps {
  currentScore: number;
  currentDebtHours: number;
  /**
   * Optional real projection payload from `/api/projection`. When
   * provided, the chart is driven by `historical_scores`,
   * `historical_debt`, and the projected endpoint from the backend.
   * When null, the chart renders an empty series without any
   * fabricated data.
   */
  projection: ApiRiskProjection | null;
}

/**
 * Build the chart series from a real projection. The series follows
 * the visual shape the chart already renders: actual historical
 * points followed by a single projected endpoint (the dashed
 * segment is rendered via `forecast`/`lowerBound`/`upperBound`).
 *
 * No fabricated data is invented: every datapoint is either a
 * historical value from the backend or the projected endpoint
 * returned by `/api/projection`.
 */
function buildSeriesFromProjection(
  projection: ApiRiskProjection | null
): TrendDataPoint[] {
  if (!projection) return [];
  const series: TrendDataPoint[] = [];
  const n = projection.historical_scores.length;
  for (let i = 0; i < n; i++) {
    series.push({
      date: (projection.historical_scanned_at[i] ?? '').slice(0, 10),
      score: projection.historical_scores[i],
      critical: 0,
      high: 0,
      debtHours: projection.historical_debt[i] ?? 0,
      commits: 0,
      driftCount: 0,
    });
  }
  if (n > 0) {
    // The projected endpoint is appended as the final point with
    // forecast bounds populated.
    series.push({
      date: projection.projected_endpoint_label || 'Projected',
      score: projection.projected_endpoint_score,
      forecast: projection.projected_endpoint_score,
      lowerBound: Math.max(
        300,
        projection.projected_endpoint_score -
          Math.max(1, Math.abs(projection.projected_endpoint_score - projection.current_score))
      ),
      upperBound: projection.projected_endpoint_score +
        Math.max(1, Math.abs(projection.projected_endpoint_score - projection.current_score)),
      critical: 0,
      high: 0,
      debtHours: projection.projected_endpoint_debt,
      commits: 0,
      driftCount: 0,
      milestone:
        projection.direction === 'improving'
          ? 'Forecast (improving)'
          : projection.direction === 'degrading'
          ? 'Forecast (degrading)'
          : projection.direction === 'flat'
          ? 'Forecast (flat)'
          : undefined,
    });
  }
  return series;
}

export const RiskProjectionChart: React.FC<RiskProjectionChartProps> = ({
  currentScore,
  currentDebtHours,
  projection,
}) => {
  const [metricMode, setMetricMode] = useState<'score' | 'debt' | 'findings'>('score');
  const [showForecast, setShowForecast] = useState<boolean>(true);
  const [burnDownTargetRate] = useState<number>(0); // Reserved for backend-supplied targets

  const chartData = buildSeriesFromProjection(projection);

  // KPI values derived directly from the real projection / history.
  const firstHistoricalScore =
    projection && projection.historical_scores.length > 0
      ? projection.historical_scores[0]
      : null;
  const lastHistoricalScore =
    projection && projection.historical_scores.length > 0
      ? projection.historical_scores[projection.historical_scores.length - 1]
      : null;
  const historicalDelta =
    firstHistoricalScore !== null && lastHistoricalScore !== null
      ? lastHistoricalScore - firstHistoricalScore
      : 0;
  const debtAccretionDelta =
    projection && projection.historical_debt.length >= 2
      ? projection.historical_debt[projection.historical_debt.length - 1] -
        projection.historical_debt[0]
      : 0;
  const projectedRecovery =
    projection && projection.projected_endpoint_label
      ? projection.projected_endpoint_label
      : '—';

  // CI gate floor target (kept as visual constant 750 — the
  // standard Code Sonar gate threshold). Only drawn when the
  // historical series actually crosses below 750, otherwise the
  // reference line would be uninformative.
  const CI_GATE_FLOOR = 750;
  const showGateReference =
    chartData.some((d) => d.score < CI_GATE_FLOOR) || currentScore < CI_GATE_FLOOR;

  return (
    <div className="p-5 rounded-xl bg-[#11161F] border border-[#2A3441] shadow-2xl relative overflow-hidden font-mono space-y-4">
      {/* Top Header & Forecast Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-[#222B38] relative z-10">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-[#3F6B8F]" />
            <h2 className="text-xs font-bold uppercase tracking-wider text-[#8FB7D9]">
              Risk Score Trend & Forecast Projection
            </h2>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40">
              RECHARTS AST ENGINE
            </span>
          </div>
          <p className="text-[11px] text-[#9CA6B2] mt-0.5">
            Historical progression of Software Risk Score with projected endpoint derived from backend scan history.
          </p>
        </div>

        {/* View Switchers & Forecast Toggle */}
        <div className="flex items-center gap-2 self-start md:self-center flex-wrap text-xs">
          {/* Metric Selector Tabs */}
          <div className="flex items-center bg-[#0B0E14] border border-[#222B38] rounded-md p-0.5">
            <button
              onClick={() => setMetricMode('score')}
              className={`px-2.5 py-1 rounded text-[11px] transition-colors ${
                metricMode === 'score'
                  ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#3F6B8F]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              Risk Score (300-850)
            </button>
            <button
              onClick={() => setMetricMode('debt')}
              className={`px-2.5 py-1 rounded text-[11px] transition-colors ${
                metricMode === 'debt'
                  ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#3F6B8F]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              Debt Hours (h)
            </button>
            <button
              onClick={() => setMetricMode('findings')}
              className={`px-2.5 py-1 rounded text-[11px] transition-colors ${
                metricMode === 'findings'
                  ? 'bg-[#1B222C] text-[#E7E9EC] font-bold border border-[#3F6B8F]/50'
                  : 'text-[#9CA6B2] hover:text-[#E7E9EC]'
              }`}
            >
              Critical / High Vectors
            </button>
          </div>

          {/* Toggle Projection */}
          <button
            onClick={() => setShowForecast(!showForecast)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] border transition-colors ${
              showForecast
                ? 'bg-[#3F6B8F]/20 text-[#8FB7D9] border-[#3F6B8F]/50'
                : 'bg-[#0B0E14] text-[#6C7989] border-[#222B38]'
            }`}
            title="Toggle projected endpoint"
          >
            <Sparkles className="w-3 h-3 text-[#E8B468]" />
            <span>{showForecast ? 'Forecast ON' : 'Forecast OFF'}</span>
          </button>
        </div>
      </div>

      {/* KPI Highlight Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div className="bg-[#0B0E14] p-3 rounded-lg border border-[#222B38]">
          <span className="text-[#6C7989] block text-[10px] uppercase">Historical Score Delta</span>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[#E7E9EC] text-base font-bold font-mono">
              {firstHistoricalScore === null
                ? '—'
                : `${historicalDelta >= 0 ? '+' : ''}${historicalDelta} pts`}
            </span>
            {firstHistoricalScore === null ? null : historicalDelta < 0 ? (
              <ArrowDownRight className="w-4 h-4 text-[#E07A7A]" />
            ) : (
              <ArrowUpRight className="w-4 h-4 text-[#7CC4A8]" />
            )}
          </div>
          <span className="text-[10px] text-[#9CA6B2]">
            {firstHistoricalScore !== null ? `From ${firstHistoricalScore} to ${currentScore}` : 'No history'}
          </span>
        </div>

        <div className="bg-[#0B0E14] p-3 rounded-lg border border-[#222B38]">
          <span className="text-[#6C7989] block text-[10px] uppercase">Technical Debt Delta</span>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[#E8B468] text-base font-bold font-mono">
              {debtAccretionDelta === 0 && currentDebtHours === 0
                ? '—'
                : `${debtAccretionDelta >= 0 ? '+' : ''}${debtAccretionDelta}h`}
            </span>
          </div>
          <span className="text-[10px] text-[#9CA6B2]">
            Total open debt: {currentDebtHours}h
          </span>
        </div>

        <div className="bg-[#0B0E14] p-3 rounded-lg border border-[#222B38]">
          <span className="text-[#6C7989] block text-[10px] uppercase">CI Gate Floor Target</span>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[#7CC4A8] text-base font-bold font-mono">≥ 750</span>
            <span className="text-[10px] text-[#E07A7A]">
              Current: {currentScore}
              {currentScore > 0 ? ` (${currentScore >= 750 ? 'Passing' : 'Deficit: ' + (750 - currentScore)})` : ''}
            </span>
          </div>
          <span className="text-[10px] text-[#9CA6B2]">Release Gating Threshold</span>
        </div>

        <div className="bg-[#0B0E14] p-3 rounded-lg border border-[#222B38]">
          <span className="text-[#6C7989] block text-[10px] uppercase">Projected Endpoint</span>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[#8FB7D9] text-base font-bold font-mono">
              {projection
                ? `${projection.projected_endpoint_score}/850`
                : '—'}
            </span>
            <Sparkles className="w-3.5 h-3.5 text-[#E8B468]" />
          </div>
          <span className="text-[10px] text-[#7CC4A8]">{projectedRecovery}</span>
        </div>
      </div>

      {/* Main Recharts Area */}
      <div className="h-72 w-full pt-2">
        {chartData.length === 0 ? (
          <div className="h-full w-full flex items-center justify-center text-center text-[11px] text-[#6C7989] font-mono">
            <div className="space-y-1">
              <div className="text-[#8FB7D9]">No scan history yet</div>
              <div>Run a scan to start the trajectory.</div>
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}>
              <defs>
                {/* Historical Score Gradient */}
                <linearGradient id="scoreHistoricalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3F6B8F" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#3F6B8F" stopOpacity={0.02} />
                </linearGradient>

                {/* Forecast Gradient */}
                <linearGradient id="scoreForecastGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#4F8A73" stopOpacity={0.5} />
                  <stop offset="95%" stopColor="#4F8A73" stopOpacity={0.02} />
                </linearGradient>

                {/* Debt Hours Gradient */}
                <linearGradient id="debtGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#C28A3D" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#C28A3D" stopOpacity={0.02} />
                </linearGradient>

                {/* Critical Findings Gradient */}
                <linearGradient id="criticalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8F3D3D" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#8F3D3D" stopOpacity={0.02} />
                </linearGradient>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke="#222B38" vertical={false} />

              <XAxis
                dataKey="date"
                stroke="#6C7989"
                tick={{ fill: '#9CA6B2', fontSize: 10, fontFamily: 'monospace' }}
                tickLine={{ stroke: '#222B38' }}
              />

              <YAxis
                domain={metricMode === 'score' ? [300, 850] : metricMode === 'debt' ? [0, 'auto'] : [0, 'auto']}
                stroke="#6C7989"
                tick={{ fill: '#9CA6B2', fontSize: 10, fontFamily: 'monospace' }}
                tickLine={{ stroke: '#222B38' }}
              />

              {/* Quality Gate Policy Target Baseline Reference Line */}
              {metricMode === 'score' && showGateReference && (
                <ReferenceLine
                  y={CI_GATE_FLOOR}
                  stroke="#E07A7A"
                  strokeDasharray="4 4"
                  label={{
                    value: 'CI Gate Minimum (750)',
                    fill: '#E07A7A',
                    fontSize: 10,
                    fontFamily: 'monospace',
                    position: 'insideTopRight',
                  }}
                />
              )}

              <Tooltip
                content={({ active, payload, label }) => {
                  if (active && payload && payload.length) {
                    const data = payload[0].payload as TrendDataPoint;
                    const isProjected =
                      typeof data.forecast === 'number' ||
                      !!data.date.match(/P\)|Projected|Forecast/i);

                    return (
                      <div className="bg-[#0B0E14] border border-[#2A3441] p-3 rounded-lg shadow-2xl font-mono text-xs space-y-1.5 min-w-[200px]">
                        <div className="flex items-center justify-between pb-1 border-b border-[#222B38]">
                          <span className="font-bold text-[#E7E9EC]">{label}</span>
                          {isProjected ? (
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#4F8A73]/20 text-[#7CC4A8] border border-[#4F8A73]/40">
                              FORECAST
                            </span>
                          ) : (
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#3F6B8F]/20 text-[#8FB7D9] border border-[#3F6B8F]/40">
                              MEASURED
                            </span>
                          )}
                        </div>

                        {data.milestone && (
                          <div className="text-[10px] text-[#E8B468] font-bold">
                            • {data.milestone}
                          </div>
                        )}

                        <div className="space-y-1 pt-1 text-[11px]">
                          <div className="flex justify-between">
                            <span className="text-[#9CA6B2]">Software Risk Score:</span>
                            <span className={`font-bold ${data.score >= 800 ? 'text-[#7CC4A8]' : data.score >= 740 ? 'text-[#E8B468]' : 'text-[#E07A7A]'}`}>
                              {data.score}/850
                            </span>
                          </div>

                          <div className="flex justify-between">
                            <span className="text-[#9CA6B2]">Technical Debt:</span>
                            <span className="text-[#8FB7D9] font-bold">{data.debtHours}h</span>
                          </div>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />

              {/* Metric Mode Renderers */}
              {metricMode === 'score' && (
                <>
                  <Area
                    type="monotone"
                    dataKey="score"
                    stroke="#3F6B8F"
                    strokeWidth={2.5}
                    fillOpacity={1}
                    fill="url(#scoreHistoricalGrad)"
                    name="Risk Score"
                  />
                  {showForecast && (
                    <Area
                      type="monotone"
                      dataKey="forecast"
                      stroke="#4F8A73"
                      strokeWidth={2}
                      strokeDasharray="4 4"
                      fillOpacity={1}
                      fill="url(#scoreForecastGrad)"
                      name="Projected"
                    />
                  )}
                </>
              )}

              {metricMode === 'debt' && (
                <Area
                  type="monotone"
                  dataKey="debtHours"
                  stroke="#C28A3D"
                  strokeWidth={2.5}
                  fillOpacity={1}
                  fill="url(#debtGrad)"
                  name="Debt Hours"
                />
              )}
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Footer Explanatory & Forecasting Assumptions for Engineering Managers */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t border-[#222B38] text-[11px] text-[#9CA6B2]">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-[#8FB7D9]">
            <span className="w-2 h-2 rounded-full bg-[#3F6B8F]" /> Historical Trend (backend-derived)
          </span>
          {showForecast && projection && (
            <span className="flex items-center gap-1.5 text-[#7CC4A8]">
              <span className="w-2 h-2 rounded-full bg-[#4F8A73]" /> Projected endpoint from /api/projection
            </span>
          )}
        </div>

        <div className="text-[10px] text-[#6C7989]">
          {projection
            ? `Direction: ${projection.direction} • Confidence: ${projection.confidence} • Horizon: ${projection.horizon}`
            : 'Awaiting backend projection.'}
        </div>
      </div>
    </div>
  );
};
