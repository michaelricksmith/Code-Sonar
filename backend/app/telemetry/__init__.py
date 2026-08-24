"""Telemetry + risk-projection layer for Code Sonar.

Real Code Sonar telemetry derived from the repository's own scan
history. No surveillance telemetry. No fabricated predictions.

This package follows the same architectural rules as
``app.drift`` and ``app.hotspots``:

- All computation lives in pure functions of ``ScanRecord`` inputs.
- ``compute_telemetry`` is a pure function of a single scan record
  plus its drift + hotspot context. Deterministic: same input ->
  byte-identical output.
- ``compute_projection`` is a pure function of a list of scan
  records. Deterministic, ordering-independent, no NaN/Inf.

The prediction engine is intentionally explainable: rolling
trend + linear regression + weighted recent trend + moving
average + finding velocity. The user always sees *why* Code Sonar
produced the projection.

Real volatility is valid information: we never alter scoring to
make projections smoother.
"""

from .telemetry_engine import (
    compute_projection,
    compute_scan_stages,
    compute_telemetry,
    compute_trend,
    compute_velocity,
)
from .telemetry_models import (
    HORIZON_7D,
    HORIZON_30D,
    HORIZON_NEXT_SCAN,
    HORIZONS,
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

__all__ = [
    "AnalyzerTelemetry",
    "HORIZON_30D",
    "HORIZON_7D",
    "HORIZON_NEXT_SCAN",
    "HORIZONS",
    "Horizon",
    "ProjectionConfidence",
    "ProjectionDirection",
    "ProjectionSignal",
    "RiskProjection",
    "RiskTrend",
    "ScanStage",
    "TelemetrySnapshot",
    "compute_projection",
    "compute_scan_stages",
    "compute_telemetry",
    "compute_trend",
    "compute_velocity",
]
