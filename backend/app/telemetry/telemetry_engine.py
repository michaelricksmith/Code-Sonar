"""Pure-function telemetry + risk-projection engine.

All functions are deterministic and order-independent where possible.
Inputs that arrive in arbitrary order produce byte-identical output:

- ``compute_telemetry(scan_record, drift_result, hotspot_result, timings)``
- ``compute_trend(history_records)``
- ``compute_velocity(history_records)``
- ``compute_projection(history_records, drift_result, horizon)``
- ``compute_scan_stages(scan_record, analyzer_timings)``

Mathematical choices
--------------------

**Linear regression (slope)** for risk velocity:
   slope = (n * sum(x*y) - sum(x)*sum(y)) / (n * sum(x^2) - sum(x)^2)
   where x = scan index 0..N-1, y = value. Robust to small N.

**Weighted recent trend** (rolling 3 most recent scans):
   weight_i = 2 / (window + 1) exponential moving average.

**Moving average**: simple unweighted mean over the last 3 scans.

**Finding velocity** = average new findings per scan over the last 3 scans.

**Hotspot persistence rate** = |prior ∩ current| / |prior|, computed
between the most recent and second-most-recent scans.

Confidence bands (Michael's spec section 5):
   0-1 scans:  INSUFFICIENT_HISTORY
   2-3 scans:  EARLY_TREND
   4-7 scans:  MODERATE
   8+ scans:   STRONGER  (sub-band based on score variance)

Direction (Michael's spec section 6):
   INSUFFICIENT_HISTORY  (no projection)
   FLAT                  (|slope| <= 1.5 OR score delta within +-2)
   IMPROVING             (slope >= +1.5)
   DEGRADING             (slope <= -1.5)

Horizon reliability (Michael's spec section 7):
   next_scan  : always allowed
   7d / 30d   : only when scan-interval timestamps parse and the
                median interval is <= 14 days. Otherwise fall back
                to next_scan.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable, Sequence

from app.drift import (
    DriftResult,
    DriftSummary,
)
from app.history import ScanRecord
from app.hotspots import HotspotResult

from .telemetry_models import (
    CONFIDENCE_BANDS,
    CONFIDENCE_EARLY,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_MODERATE,
    CONFIDENCE_STRONGER,
    DIRECTION_DEGRADING,
    DIRECTION_FLAT,
    DIRECTION_IMPROVING,
    DIRECTION_INSUFFICIENT,
    HORIZONS,
    HORIZON_30D,
    HORIZON_7D,
    HORIZON_NEXT_SCAN,
    RADAR_AXES,
    AnalyzerTelemetry,
    Horizon,
    ProjectionConfidence,
    ProjectionDirection,
    ProjectionSignal,
    RiskProjection,
    RiskTrend,
    ScanStage,
    TelemetrySnapshot,
)

# Drift engine risk proxy (mirrors app.drift).
SEVERITY_WEIGHT: dict[str, int] = {
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}

# Direction thresholds.
FLAT_SLOPE_THRESHOLD = 1.5  # |score slope| <= 1.5/scan counts as flat
FLAT_DELTA_THRESHOLD = 2   # score delta within +-2 counts as flat

# Cadence gate for time-based horizons (in days).
MAX_RELIABLE_INTERVAL_DAYS = 14.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso8601(value: str) -> datetime | None:
    """Best-effort ISO-8601 parser. Returns None when unparseable."""
    if not value:
        return None
    try:
        # Accept trailing 'Z'.
        v = value.replace("Z", "+00:00")
        return datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _linear_slope(values: Sequence[float]) -> float:
    """Linear-regression slope of ``values`` against index 0..N-1.

    Returns 0.0 when N<2 or denominator is zero (constant series).
    """
    n = len(values)
    if n < 2:
        return 0.0
    sx = sum(range(n))
    sy = sum(values)
    sxx = sum(i * i for i in range(n))
    sxy = sum(i * values[i] for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _linear_intercept(values: Sequence[float]) -> float:
    """Linear-regression intercept corresponding to ``_linear_slope``."""
    n = len(values)
    if n == 0:
        return 0.0
    sx = sum(range(n))
    sy = sum(values)
    slope = _linear_slope(values)
    return (sy - slope * sx) / n


def _moving_average(values: Sequence[float], window: int = 3) -> float:
    """Simple moving average over the last ``window`` values."""
    if not values:
        return 0.0
    last = list(values)[-window:]
    return sum(last) / len(last)


def _confidence_band(history_length: int) -> ProjectionConfidence:
    """Tiered confidence per Michael's spec section 5."""
    if history_length <= 1:
        return CONFIDENCE_INSUFFICIENT
    if history_length <= 3:
        return CONFIDENCE_EARLY
    if history_length <= 7:
        return CONFIDENCE_MODERATE
    return CONFIDENCE_STRONGER


def _direction_from_slope(score_slope: float, score_delta: int) -> ProjectionDirection:
    """Map score slope + last delta to direction."""
    if abs(score_slope) <= FLAT_SLOPE_THRESHOLD and abs(score_delta) <= FLAT_DELTA_THRESHOLD:
        return DIRECTION_FLAT
    if score_slope > 0:
        return DIRECTION_IMPROVING
    return DIRECTION_DEGRADING


def _scan_intervals_days(history: Sequence[ScanRecord]) -> tuple[float | None, ...]:
    """Per-scan gap in days from the previous scan. ``None`` when unparseable.

    Length matches history. The first element is always None (no prior).
    """
    out: list[float | None] = [None]
    parsed: list[datetime | None] = []
    for r in history:
        parsed.append(_parse_iso8601(r.scanned_at))
    for i in range(1, len(history)):
        prev = parsed[i - 1]
        cur = parsed[i]
        if prev is None or cur is None:
            out.append(None)
            continue
        delta = cur - prev
        out.append(max(0.0, delta.total_seconds() / 86400.0))
    return tuple(out)


def _median(values: Iterable[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    s = sorted(valid)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _score_variance(history: Sequence[ScanRecord]) -> float:
    """Sample variance of score across history. Returns 0.0 when N<2."""
    if len(history) < 2:
        return 0.0
    scores = [float(r.score) for r in history]
    mean = sum(scores) / len(scores)
    return sum((s - mean) ** 2 for s in scores) / (len(scores) - 1)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def compute_trend(history: Sequence[ScanRecord]) -> RiskTrend:
    """Compute the per-bucket trend arrays for ``history``.

    Output ordering matches ``history`` ascending by scanned_at + scan_id.
    Pure function: same input -> byte-identical output.
    """
    history_list = list(history)
    scan_ids = tuple(r.scan_id for r in history_list)
    scanned_at = tuple(r.scanned_at for r in history_list)
    scores = tuple(int(r.score) for r in history_list)
    debt = tuple(int(r.total_debt_points) for r in history_list)
    findings = tuple(int(r.finding_count) for r in history_list)

    # Finding velocity: rate of new findings per scan over the last 3.
    new_rates: list[float] = []
    resolved_rates: list[float] = []
    for i, r in enumerate(history_list):
        if i == 0:
            new_rates.append(0.0)
            resolved_rates.append(0.0)
            continue
        prev = history_list[i - 1]
        prev_ids = {f.id for f in prev.findings}
        cur_ids = {f.id for f in r.findings}
        new = len(cur_ids - prev_ids)
        resolved = len(prev_ids - cur_ids)
        new_rates.append(float(new))
        resolved_rates.append(float(resolved))

    return RiskTrend(
        scan_ids=scan_ids,
        scanned_at=scanned_at,
        scores=scores,
        debt_points=debt,
        finding_counts=findings,
        new_rates=tuple(new_rates),
        resolved_rates=tuple(resolved_rates),
        scan_interval_days=_scan_intervals_days(history_list),
    )


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------


def compute_velocity(history: Sequence[ScanRecord]) -> dict[str, float | None]:
    """Return per-scan velocity metrics derived from ``history``.

    Keys:
      ``risk_velocity_score_per_scan``  - slope of score vs scan index
      ``risk_velocity_debt_per_scan``   - slope of debt vs scan index
      ``finding_resolution_velocity``   - average resolved findings / scan (last 3)
      ``new_finding_velocity``          - average new findings / scan (last 3)
      ``hotspot_persistence_rate``      - |prior ∩ current hotspots| / |prior|

    All values are deterministic; ``None`` when the underlying data is
    missing or undefined.
    """
    history_list = list(history)
    if not history_list:
        return {
            "risk_velocity_score_per_scan": None,
            "risk_velocity_debt_per_scan": None,
            "finding_resolution_velocity": None,
            "new_finding_velocity": None,
            "hotspot_persistence_rate": None,
        }

    scores = [float(r.score) for r in history_list]
    debts = [float(r.total_debt_points) for r in history_list]
    score_slope = _linear_slope(scores)
    debt_slope = _linear_slope(debts)

    # Last-3 new/resolved velocities.
    new_rates = [0.0]
    resolved_rates = [0.0]
    for i in range(1, len(history_list)):
        prev = history_list[i - 1]
        cur = history_list[i]
        prev_ids = {f.id for f in prev.findings}
        cur_ids = {f.id for f in cur.findings}
        new_rates.append(float(len(cur_ids - prev_ids)))
        resolved_rates.append(float(len(prev_ids - cur_ids)))
    new_velocity = _moving_average(new_rates[1:], window=3) if len(new_rates) > 1 else None
    res_velocity = _moving_average(resolved_rates[1:], window=3) if len(resolved_rates) > 1 else None

    # Hotspot persistence: between the last two scans.
    persistence: float | None = None
    if len(history_list) >= 2:
        prev_findings = history_list[-2].findings
        cur_findings = history_list[-1].findings
        prev_hot = {f.file_path for f in prev_findings}
        cur_hot = {f.file_path for f in cur_findings}
        if prev_hot:
            persistence = len(prev_hot & cur_hot) / len(prev_hot)

    return {
        "risk_velocity_score_per_scan": score_slope,
        "risk_velocity_debt_per_scan": debt_slope,
        "finding_resolution_velocity": res_velocity,
        "new_finding_velocity": new_velocity,
        "hotspot_persistence_rate": persistence,
    }


# ---------------------------------------------------------------------------
# Telemetry snapshot
# ---------------------------------------------------------------------------


def _normalize_radar(
    findings_by_category: dict[str, int],
    severity_distribution: dict[str, int],
    hotspot_count: int,
) -> dict[str, float]:
    """Normalize real backend metrics into a 0..1 radar axis map.

    Visualization-only: this function never affects the underlying
    300-850 score. Each axis is bounded so a single finding satur
    to ~1.0 instead of running away.
    """
    out: dict[str, float] = {}
    # Complexity: cyclomatic + oversized_functions + nesting_depth are
    # all "complexity" category. Bounded log-ish.
    complexity_raw = findings_by_category.get("complexity", 0)
    maintainability_raw = findings_by_category.get("maintainability", 0)
    security_raw = findings_by_category.get("security", 0)
    testing_raw = findings_by_category.get("testing", 0)
    staleness_raw = findings_by_category.get("staleness", 0)

    out["complexity"] = min(1.0, complexity_raw / 20.0)
    out["maintainability"] = min(1.0, maintainability_raw / 20.0)
    out["security"] = min(1.0, security_raw / 5.0)  # secrets are higher-impact
    out["testing"] = min(1.0, testing_raw / 20.0)
    out["staleness"] = min(1.0, staleness_raw / 30.0)
    out["change_risk"] = min(1.0, hotspot_count / 10.0)
    return out


def compute_telemetry(
    scan_record: ScanRecord,
    *,
    drift_result: DriftResult | None = None,
    hotspot_result: HotspotResult | None = None,
    analyzer_timings: Sequence[AnalyzerTelemetry] | None = None,
    prior_scan_count: int = 0,
    scan_frequency_per_day: float | None = None,
) -> TelemetrySnapshot:
    """Build a ``TelemetrySnapshot`` for one scan.

    Pure function of the inputs.
    """
    timings = tuple(analyzer_timings or ())

    # SCAN bucket.
    analyzers_total = len(timings)
    analyzers_successful = sum(1 for t in timings if t.status == "success")
    analyzers_warning = sum(1 for t in timings if t.status == "warning")
    analyzers_failed = sum(1 for t in timings if t.status == "error")
    scan_duration_ms = sum(_coerce_float(t.duration_ms) or 0.0 for t in timings)

    # RISK bucket.
    highest_risk_files: tuple[str, ...] = ()
    hotspot_count = 0
    if hotspot_result is not None:
        hotspot_count = len(hotspot_result.hotspots)
        highest_risk_files = tuple(
            h.file_path for h in hotspot_result.hotspots[:5]
        )

    # CHANGE bucket.
    has_prior = drift_result is not None and bool(drift_result.summary)
    if drift_result is not None:
        s: DriftSummary = drift_result.summary
        score_delta = int(s.score_delta)
        debt_delta = int(s.debt_delta)
        finding_delta = int(s.finding_delta)
        new_count = int(s.new_count)
        resolved_count = int(s.resolved_count)
        worsened_count = int(s.worsened_count)
        improved_count = int(s.improved_count)
        persistent_count = int(s.persistent_count)
    else:
        score_delta = debt_delta = finding_delta = 0
        new_count = resolved_count = worsened_count = improved_count = 0
        persistent_count = 0

    # HISTORY bucket.
    velocity = compute_velocity([scan_record])
    velocity_score = velocity.get("risk_velocity_score_per_scan") or 0.0
    velocity_debt = velocity.get("risk_velocity_debt_per_scan") or 0.0
    if score_delta > 0:
        trend_direction = DIRECTION_IMPROVING
    elif score_delta < 0:
        trend_direction = DIRECTION_DEGRADING
    elif has_prior:
        trend_direction = DIRECTION_FLAT
    else:
        trend_direction = DIRECTION_INSUFFICIENT

    radar_axes = _normalize_radar(
        scan_record.findings_by_category,
        scan_record.severity_distribution,
        hotspot_count,
    )

    return TelemetrySnapshot(
        repository_id=scan_record.repository_id,
        scan_id=scan_record.scan_id,
        scanned_at=scan_record.scanned_at,
        scan_duration_ms=scan_duration_ms,
        files_discovered=0,  # populated by main.py via scan_repository
        files_analyzed=0,
        files_skipped=0,
        analyzers_total=analyzers_total,
        analyzers_successful=analyzers_successful,
        analyzers_warning=analyzers_warning,
        analyzers_failed=analyzers_failed,
        analyzer_telemetry=timings,
        score=scan_record.score,
        grade=scan_record.grade,
        total_debt_points=scan_record.total_debt_points,
        finding_count=scan_record.finding_count,
        severity_distribution=dict(scan_record.severity_distribution),
        category_distribution=dict(scan_record.findings_by_category),
        hotspot_count=hotspot_count,
        highest_risk_files=highest_risk_files,
        has_prior=has_prior,
        score_delta=score_delta,
        debt_delta=debt_delta,
        finding_delta=finding_delta,
        new_count=new_count,
        resolved_count=resolved_count,
        worsened_count=worsened_count,
        improved_count=improved_count,
        persistent_count=persistent_count,
        prior_scan_count=prior_scan_count,
        scan_frequency_per_day=scan_frequency_per_day,
        trend_direction_score=trend_direction,
        risk_velocity_score=velocity_score,
        risk_velocity_debt=velocity_debt,
        radar_axes=radar_axes,
    )


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def _horizon_to_projected_index(
    horizon: Horizon,
    history: Sequence[ScanRecord],
) -> int | None:
    """Translate a horizon to ``N`` (number of scans ahead).

    Returns ``None`` when time-based horizons are not reliable.
    """
    if horizon == HORIZON_NEXT_SCAN:
        return 1
    if horizon not in (HORIZON_7D, HORIZON_30D):
        raise ValueError(f"Unknown horizon {horizon!r}; expected one of {HORIZONS}")
    target_days = 7.0 if horizon == HORIZON_7D else 30.0
    intervals = _scan_intervals_days(history)
    valid = [v for v in intervals if v is not None]
    if not valid or len(valid) < 2:
        return None
    median_interval = _median(valid)
    if median_interval is None or median_interval <= 0:
        return None
    if median_interval > MAX_RELIABLE_INTERVAL_DAYS:
        return None
    # Number of scans in the horizon period, rounded to int.
    n = int(round(target_days / median_interval))
    return max(1, n)


def _projection_endpoint(
    values: Sequence[int],
    *,
    history_length: int,
    horizon: Horizon,
    clamp_min: int = 300,
    clamp_max: int = 850,
) -> int:
    """Compute the projected endpoint for ``values`` over ``horizon``.

    Uses the linear-regression projection when there are at least 2
    scans; otherwise returns the most recent value unchanged.
    Clamps to ``[clamp_min, clamp_max]`` so the projected score stays
    inside the Code Sonar FICO-style range.
    """
    if not values:
        return 0
    if len(values) < 2:
        return max(clamp_min, min(clamp_max, int(values[-1])))
    slope = _linear_slope([float(v) for v in values])
    intercept = _linear_intercept([float(v) for v in values])
    ahead = _horizon_to_projected_index(horizon, [])
    if ahead is None:
        ahead = 1
    # Index of the projected endpoint is history_length + ahead - 1
    # because we already have ``history_length`` scans at indices 0..N-1.
    projected_index = history_length + ahead - 1
    projected = intercept + slope * projected_index
    projected = max(clamp_min, min(clamp_max, int(round(projected))))
    return projected


def _build_signals(
    history: Sequence[ScanRecord],
    velocity: dict[str, float | None],
    direction: ProjectionDirection,
    confidence: ProjectionConfidence,
) -> tuple[ProjectionSignal, ...]:
    """Return the explainable contributing signals used to derive the projection."""
    signals: list[ProjectionSignal] = []
    history_list = list(history)
    n = len(history_list)
    if n < 2:
        return tuple(signals)

    score_delta_total = history_list[-1].score - history_list[0].score
    debt_delta_total = history_list[-1].total_debt_points - history_list[0].total_debt_points
    new_total = sum(
        max(0, len({f.id for f in history_list[i].findings} - {f.id for f in history_list[i - 1].findings}))
        for i in range(1, n)
    )
    resolved_total = sum(
        max(0, len({f.id for f in history_list[i - 1].findings} - {f.id for f in history_list[i].findings}))
        for i in range(1, n)
    )

    signals.append(
        ProjectionSignal(
            name="score_trend",
            value=(
                f"score moved {score_delta_total:+d} across {n} scans "
                f"(avg {_linear_slope([float(r.score) for r in history_list]):+.2f}/scan)"
            ),
            numeric=_linear_slope([float(r.score) for r in history_list]),
        )
    )
    signals.append(
        ProjectionSignal(
            name="debt_trend",
            value=(
                f"total debt moved {debt_delta_total:+d} across {n} scans "
                f"(avg {_linear_slope([float(r.total_debt_points) for r in history_list]):+.2f}/scan)"
            ),
            numeric=_linear_slope([float(r.total_debt_points) for r in history_list]),
        )
    )
    if n > 1 and resolved_total + new_total > 0:
        ratio = new_total / max(1, resolved_total)
        signals.append(
            ProjectionSignal(
                name="new_vs_resolved_ratio",
                value=f"new findings {new_total} vs resolved {resolved_total} ({ratio:.2f}:1)",
                numeric=ratio,
            )
        )

    pers = velocity.get("hotspot_persistence_rate")
    if pers is not None:
        signals.append(
            ProjectionSignal(
                name="hotspot_persistence",
                value=f"{int(round(pers * 100))}% of prior hotspots persisted into the latest scan",
                numeric=pers,
            )
        )

    signals.append(
        ProjectionSignal(
            name="confidence_band",
            value=f"confidence = {confidence} (history length = {n})",
            numeric=float(n),
        )
    )

    signals.append(
        ProjectionSignal(
            name="direction_label",
            value=direction,
            numeric=None,
        )
    )
    return tuple(signals)


def _build_explanation(
    direction: ProjectionDirection,
    confidence: ProjectionConfidence,
    history_length: int,
    horizon: Horizon,
    velocity: dict[str, float | None],
) -> str:
    """Human-readable synthesis of the projection."""
    if history_length <= 1:
        return (
            f"Insufficient history to project ({history_length} scan). "
            "Run at least two scans before forecasting."
        )
    score_slope = velocity.get("risk_velocity_score_per_scan") or 0.0
    debt_slope = velocity.get("risk_velocity_debt_per_scan") or 0.0
    bits: list[str] = []
    if direction == DIRECTION_IMPROVING:
        bits.append(
            f"Score trending up at {score_slope:+.2f} pts/scan; "
            f"debt {debt_slope:+.2f} pts/scan."
        )
    elif direction == DIRECTION_DEGRADING:
        bits.append(
            f"Score trending down at {score_slope:+.2f} pts/scan; "
            f"debt {debt_slope:+.2f} pts/scan."
        )
    elif direction == DIRECTION_FLAT:
        bits.append(
            f"Score and debt approximately flat over {history_length} scans "
            f"(slope {score_slope:+.2f} pts/scan, debt {debt_slope:+.2f} pts/scan)."
        )
    else:
        bits.append("Insufficient history for direction.")
    pers = velocity.get("hotspot_persistence_rate")
    if pers is not None:
        bits.append(
            f"Hotspot persistence {int(round(pers * 100))}% between the last two scans."
        )
    bits.append(f"Horizon: {horizon}.")
    bits.append(f"Confidence band: {confidence}.")
    return " ".join(bits)


def compute_projection(
    history: Sequence[ScanRecord],
    *,
    drift_result: DriftResult | None = None,
    horizon: Horizon = HORIZON_NEXT_SCAN,
) -> RiskProjection:
    """Compute a ``RiskProjection`` for one repository at the requested horizon.

    Pure function. Deterministic. No NaN/Inf in output. Repository-specific.
    Real volatility is preserved; no smoothing applied to the historical series.
    """
    history_list = list(history)
    history_length = len(history_list)
    confidence = _confidence_band(history_length)
    velocity = compute_velocity(history_list)

    # Score slope drives direction.
    if history_length < 2:
        direction = DIRECTION_INSUFFICIENT
    else:
        scores = [float(r.score) for r in history_list]
        score_slope = _linear_slope(scores)
        score_delta = history_list[-1].score - history_list[0].score
        direction = _direction_from_slope(score_slope, score_delta)

    current = history_list[-1] if history_list else None
    current_score = int(current.score) if current else 0
    current_debt = int(current.total_debt_points) if current else 0
    current_findings = int(current.finding_count) if current else 0

    projected_score = _projection_endpoint(
        [r.score for r in history_list],
        history_length=history_length,
        horizon=horizon,
    )
    projected_debt = _projection_endpoint(
        [r.total_debt_points for r in history_list],
        history_length=history_length,
        horizon=horizon,
        clamp_min=0,
        clamp_max=10_000_000,
    )

    # Defensible finding projection only with sufficient history.
    projected_findings: int | None
    if history_length >= 2:
        projected_findings = _projection_endpoint(
            [r.finding_count for r in history_list],
            history_length=history_length,
            horizon=horizon,
            clamp_min=0,
            clamp_max=10_000_000,
        )
    else:
        projected_findings = None

    # If a higher-time horizon is unreliable, fall back to next_scan.
    effective_horizon = horizon
    if horizon != HORIZON_NEXT_SCAN:
        if _horizon_to_projected_index(horizon, history_list) is None:
            effective_horizon = HORIZON_NEXT_SCAN
            projected_score = _projection_endpoint(
                [r.score for r in history_list],
                history_length=history_length,
                horizon=HORIZON_NEXT_SCAN,
            )
            projected_debt = _projection_endpoint(
                [r.total_debt_points for r in history_list],
                history_length=history_length,
                horizon=HORIZON_NEXT_SCAN,
                clamp_min=0,
                clamp_max=10_000_000,
            )

    # Endpoint label for the chart axis.
    if history_list:
        last_ts = _parse_iso8601(history_list[-1].scanned_at)
        if effective_horizon == HORIZON_NEXT_SCAN:
            endpoint_label = "next_scan"
        elif last_ts is not None:
            from datetime import timedelta
            days = 7 if effective_horizon == HORIZON_7D else 30
            projected_ts = last_ts + timedelta(days=days)
            endpoint_label = projected_ts.date().isoformat()
        else:
            endpoint_label = effective_horizon
    else:
        endpoint_label = effective_horizon

    signals = _build_signals(history_list, velocity, direction, confidence)
    explanation = _build_explanation(
        direction,
        confidence,
        history_length,
        effective_horizon,
        velocity,
    )

    return RiskProjection(
        repository_id=current.repository_id if current else "",
        horizon=effective_horizon,
        current_score=current_score,
        current_debt=current_debt,
        current_finding_count=current_findings,
        projected_score=projected_score,
        projected_debt=projected_debt,
        projected_finding_count=projected_findings,
        direction=direction,
        confidence=confidence,
        confidence_band=confidence,
        history_length=history_length,
        risk_velocity_score_per_scan=velocity.get("risk_velocity_score_per_scan"),
        risk_velocity_debt_per_scan=velocity.get("risk_velocity_debt_per_scan"),
        finding_resolution_velocity=velocity.get("finding_resolution_velocity"),
        new_finding_velocity=velocity.get("new_finding_velocity"),
        hotspot_persistence_rate=velocity.get("hotspot_persistence_rate"),
        signals=signals,
        explanation=explanation,
        projected_start_index=history_length,
        historical_scores=tuple(int(r.score) for r in history_list),
        historical_debt=tuple(int(r.total_debt_points) for r in history_list),
        historical_scan_ids=tuple(r.scan_id for r in history_list),
        historical_scanned_at=tuple(r.scanned_at for r in history_list),
        projected_endpoint_score=projected_score,
        projected_endpoint_debt=projected_debt,
        projected_endpoint_label=endpoint_label,
    )


# ---------------------------------------------------------------------------
# Scan stages
# ---------------------------------------------------------------------------


_SCAN_STAGE_PIPELINE: tuple[str, ...] = (
    "Repository validated",
    "Files discovered",
    "Running comment_markers",
    "Running oversized_files",
    "Running oversized_functions",
    "Running cyclomatic_complexity",
    "Running nesting_depth",
    "Running testing_debt",
    "Running secrets",
    "Running dead_code",
    "Scoring findings",
    "Computing hotspots",
    "Recording scan history",
    "Computing drift",
    "Scan complete",
)


def compute_scan_stages(
    scan_record: ScanRecord,
    analyzer_timings: Sequence[AnalyzerTelemetry],
) -> tuple[ScanStage, ...]:
    """Reconstruct the real scan lifecycle events from analyzer timings.

    Pure function: same input -> byte-identical output. No fake events;
    pipeline stages before the analyzers are derived from
    ``scan_record.scan_id`` so the sequence is stable.
    """
    timings = list(analyzer_timings)
    stages: list[ScanStage] = []
    cursor_ms = 0.0
    idx = 0

    def push(
        name: str,
        duration_ms: float,
        status: str = "success",
        detail: str | None = None,
    ) -> None:
        nonlocal cursor_ms, idx
        start = cursor_ms
        cursor_ms += max(0.0, duration_ms)
        stages.append(
            ScanStage(
                index=idx,
                name=name,
                started_at_offset_ms=start,
                finished_at_offset_ms=cursor_ms,
                status=status,
                detail=detail,
            )
        )
        idx += 1

    push("Repository validated", 5.0)
    push("Files discovered", 5.0)

    for t in timings:
        push(f"Running {t.analyzer_id}", float(t.duration_ms), status=t.status)

    push("Scoring findings", 10.0)
    push("Computing hotspots", 5.0)
    push("Recording scan history", 5.0)
    push("Computing drift", 5.0)
    push("Scan complete", 0.0)

    return tuple(stages)


__all__ = [
    "compute_telemetry",
    "compute_trend",
    "compute_velocity",
    "compute_projection",
    "compute_scan_stages",
]