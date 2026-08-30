"""Data classes for telemetry + projection output.

All classes are ``@dataclass(frozen=True)`` so they are
hashable, deterministic, and JSON-serialisable via ``to_dict``.

The schema mirrors Michael's spec sections 13 (API/Model design):
- ``TelemetrySnapshot``
- ``AnalyzerTelemetry``
- ``RiskTrend``
- ``RiskProjection``
- ``ProjectionSignal``
- ``ProjectionConfidence``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


# Tiered confidence (Michael's spec section 5):
#   0-1 scans:  INSUFFICIENT_HISTORY
#   2-3 scans:  EARLY_TREND
#   4-7 scans:  MODERATE
#   8+ scans:   STRONGER (with sub-band based on variance)
CONFIDENCE_INSUFFICIENT = "insufficient_history"
CONFIDENCE_EARLY = "early_trend"
CONFIDENCE_MODERATE = "moderate"
CONFIDENCE_STRONGER = "stronger"

CONFIDENCE_BANDS: tuple[str, ...] = (
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_EARLY,
    CONFIDENCE_MODERATE,
    CONFIDENCE_STRONGER,
)


# Forecast horizons (Michael's spec section 7):
HORIZON_NEXT_SCAN = "next_scan"
HORIZON_7D = "7d"
HORIZON_30D = "30d"

HORIZONS: tuple[str, ...] = (HORIZON_NEXT_SCAN, HORIZON_7D, HORIZON_30D)


# Projection direction (Michael's spec section 6):
DIRECTION_INSUFFICIENT = "insufficient_history"
DIRECTION_IMPROVING = "improving"
DIRECTION_DEGRADING = "degrading"
DIRECTION_FLAT = "flat"

DIRECTIONS: tuple[str, ...] = (
    DIRECTION_INSUFFICIENT,
    DIRECTION_IMPROVING,
    DIRECTION_DEGRADING,
    DIRECTION_FLAT,
)


# Sonar Radar HUD axes (Michael's spec section 12).
# Only real Code Sonar categories that the analyzer pipeline
# actually produces. No fabricated metrics.
RADAR_AXES: tuple[str, ...] = (
    "complexity",
    "maintainability",
    "security",
    "testing",
    "staleness",
    "change_risk",
)


def horizon_type(name: str) -> str:
    """Validated horizon string. Returns ``name`` when valid."""
    if name not in HORIZONS:
        raise ValueError(
            f"Unknown horizon {name!r}; expected one of {HORIZONS}"
        )
    return name


ProjectionConfidence = str  # alias for type hint readability
ProjectionDirection = str   # alias for type hint readability
Horizon = str               # alias for type hint readability


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyzerTelemetry:
    """Per-analyzer timing + status from one scan."""

    analyzer_id: str
    findings_count: int
    duration_ms: float
    status: str  # "success" | "warning" | "error" | "skipped"
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Software Risk Telemetry for a single scan.

    Four logical buckets per Michael's spec section 1:
      SCAN    - per-analyzer timing + status
      RISK    - score / grade / debt / finding count / severity dist
      CHANGE  - drift deltas (vs prior scan if available)
      HISTORY - cadence + cumulative repository stats
    """

    repository_id: str
    scan_id: str
    scanned_at: str

    # SCAN bucket
    scan_duration_ms: float
    files_discovered: int
    files_analyzed: int
    files_skipped: int
    analyzers_total: int
    analyzers_successful: int
    analyzers_warning: int
    analyzers_failed: int
    analyzer_telemetry: tuple[AnalyzerTelemetry, ...]

    # RISK bucket
    score: int
    grade: str
    total_debt_points: int
    finding_count: int
    severity_distribution: dict[str, int]
    category_distribution: dict[str, int]
    hotspot_count: int
    highest_risk_files: tuple[str, ...]

    # CHANGE bucket (vs prior scan; empty when no prior scan exists)
    has_prior: bool
    score_delta: int
    debt_delta: int
    finding_delta: int
    new_count: int
    resolved_count: int
    worsened_count: int
    improved_count: int
    persistent_count: int

    # HISTORY bucket
    prior_scan_count: int
    scan_frequency_per_day: float | None
    trend_direction_score: str  # same enum as ProjectionDirection
    risk_velocity_score: float | None  # score points per scan (signed)
    risk_velocity_debt: float | None   # debt points per scan (signed)

    # Radar axes (normalized 0..1, visualization-only)
    radar_axes: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["analyzer_telemetry"] = [a.to_dict() for a in self.analyzer_telemetry]
        d["highest_risk_files"] = list(self.highest_risk_files)
        return d


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskTrend:
    """Per-scan history arrays for one repository.

    Length-N where N == ``len(history_records)``. Order matches
    ``history_records`` (ascending ``scanned_at`` then ``scan_id``).

    Cadence is reported in days; ``None`` when the scan interval is
    not reliable (irregular timestamps, <2 scans).
    """

    scan_ids: tuple[str, ...]
    scanned_at: tuple[str, ...]
    scores: tuple[int, ...]
    debt_points: tuple[int, ...]
    finding_counts: tuple[int, ...]
    new_rates: tuple[float, ...]
    resolved_rates: tuple[float, ...]
    scan_interval_days: tuple[float | None, ...]

    @property
    def length(self) -> int:
        return len(self.scan_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionSignal:
    """A single contributing signal in a ``RiskProjection``.

    Each signal is a derived fact about the repository's history
    that contributes to the projection. The user can read the
    signals and verify the forecast themselves.
    """

    name: str
    value: str  # human-readable
    numeric: float | None = None  # optional numeric value for tooling

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskProjection:
    """Forecast for one repository at a requested horizon.

    Per Michael's spec section 6: always includes
    current + projected + horizon + direction + confidence
    + contributing signals + explanation. The explanation is a
    human-readable synthesis the user can read to understand
    why Code Sonar produced the projection.
    """

    repository_id: str
    horizon: Horizon
    current_score: int
    current_debt: int
    current_finding_count: int
    projected_score: int
    projected_debt: int
    projected_finding_count: int | None  # None when not defensible
    direction: ProjectionDirection
    confidence: ProjectionConfidence
    confidence_band: str
    history_length: int

    risk_velocity_score_per_scan: float | None
    risk_velocity_debt_per_scan: float | None
    finding_resolution_velocity: float | None
    new_finding_velocity: float | None
    hotspot_persistence_rate: float | None

    signals: tuple[ProjectionSignal, ...]
    explanation: str

    # Discrete-actual vs projected boundary: indices into the
    # history series where the projected band starts. Lets the
    # chart render a dashed segment for forecasted values.
    projected_start_index: int

    # The raw historical arrays (same shape as ``RiskTrend``).
    # Chart code uses these + projected endpoints to render
    # actual-vs-projected distinctly.
    historical_scores: tuple[int, ...]
    historical_debt: tuple[int, ...]
    historical_scan_ids: tuple[str, ...]
    historical_scanned_at: tuple[str, ...]

    # Endpoints the chart appends to draw the projected segment.
    projected_endpoint_score: int
    projected_endpoint_debt: int
    projected_endpoint_label: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d


# ---------------------------------------------------------------------------
# Scan stage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanStage:
    """A real lifecycle event in a scan.

    Used by ``LiveScanTerminal`` to render the actual sequence
    of events that happened during a scan (analyzer start/end,
    scoring, drift computation, complete). Stages are
    reconstructed deterministically from analyzer telemetry; no
    fake events.
    """

    index: int
    name: str  # "Repository validated", "Running comment_markers", ...
    started_at_offset_ms: float  # ms since scan start
    finished_at_offset_ms: float
    status: str  # "success" | "warning" | "error" | "info"
    detail: str | None = None

    @property
    def duration_ms(self) -> float:
        return max(0.0, self.finished_at_offset_ms - self.started_at_offset_ms)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d
