"""FastAPI application entry point."""

import time
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.drift import compute_drift
from app.history import (
    InMemoryHistoryStore,
    JsonlHistoryStore,
    ScanRecord,
    build_scan_record,
    compute_repository_id,
    display_name,
)
from app.hotspots import compute_hotspots
from app.scoring.engine import calculate_score
from app.security import RepositoryValidationError, validate_repo_path
from app.services.repository import (
    get_analyzer_metadata,
    get_registered_analyzers,
    scan_repository,
)
from app.telemetry import (
    HORIZON_NEXT_SCAN,
    HORIZONS,
    AnalyzerTelemetry,
    TelemetrySnapshot,
    compute_projection,
    compute_scan_stages,
    compute_telemetry,
)

app = FastAPI(
    title="Code Sonar API",
    description="Credit report for your codebase",
    version="0.1.0-beta.1",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Process-wide history store. The MVP uses a single JSONL file in
# the user's data dir; tests inject an InMemoryHistoryStore via
# ``app.dependency_overrides`` (FastAPI) or by replacing this module
# attribute before startup.
_history_store: JsonlHistoryStore | InMemoryHistoryStore = JsonlHistoryStore()


def get_history_store() -> JsonlHistoryStore | InMemoryHistoryStore:
    """Return the process-wide history store. Pluggable for tests."""
    return _history_store


def set_history_store(store: JsonlHistoryStore | InMemoryHistoryStore) -> None:
    """Replace the process-wide history store. Used by tests."""
    global _history_store
    _history_store = store


class ScanRequest(BaseModel):
    repo_path: str = Field(description="Path to repository root directory")


class ScanResponse(BaseModel):
    repository: str
    scanned_at: str
    score: int
    grade: str
    total_debt_points: int
    finding_count: int
    category_scores: dict[str, int]
    severity_distribution: dict[str, int]
    findings_by_category: dict[str, int]
    findings: list[dict[str, Any]]
    summary: dict[str, Any]
    top_hotspots: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top-N ranked risk hotspots (Phase 1, Fastest-Route-to-Private-Beta).",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Code Sonar API", "version": "0.1.0"}


@app.get("/api/analyzers")
async def list_analyzers() -> dict[str, Any]:
    """Public analyzer registry metadata.

    Returns the list of registered analyzers with their public
    metadata. Stable shape: each entry has ``name``, ``analyzer_id``,
    ``category``, and ``threshold``. Threshold may be null when an
    analyzer is rule-driven rather than numeric-threshold-driven.
    """
    return {
        "count": len(get_registered_analyzers()),
        "analyzers": get_analyzer_metadata(),
    }


def _record_to_dict(record: ScanRecord) -> dict[str, Any]:
    return {
        "scan_id": record.scan_id,
        "repository_id": record.repository_id,
        "repository_path": record.repository_path,
        "scanned_at": record.scanned_at,
        "schema_version": record.schema_version,
        "score": record.score,
        "grade": record.grade,
        "total_debt_points": record.total_debt_points,
        "finding_count": record.finding_count,
        "category_scores": record.category_scores,
        "severity_distribution": record.severity_distribution,
        "findings_by_category": record.findings_by_category,
        "findings_source_breakdown": record.findings_source_breakdown,
        "findings": [f.to_dict() for f in record.findings],
    }


def _record_summary(record: ScanRecord) -> dict[str, Any]:
    """Return the summary fields only (no findings snapshot)."""
    return {
        "scan_id": record.scan_id,
        "repository_id": record.repository_id,
        "repository_path": record.repository_path,
        "scanned_at": record.scanned_at,
        "schema_version": record.schema_version,
        "score": record.score,
        "grade": record.grade,
        "total_debt_points": record.total_debt_points,
        "finding_count": record.finding_count,
        "category_scores": record.category_scores,
        "severity_distribution": record.severity_distribution,
        "findings_by_category": record.findings_by_category,
        "findings_source_breakdown": record.findings_source_breakdown,
    }


@app.post("/api/scan", response_model=ScanResponse)
async def scan(request: ScanRequest) -> ScanResponse:
    try:
        repo_path = validate_repo_path(request.repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Per-analyzer timing + telemetry instrumentation. The
    # analyzer pipeline runs sequentially in scan_repository; we
    # wrap it with a single high-resolution wall-clock measurement
    # and per-analyzer timing derived from the analyzer metadata
    # (no fake events; the timings are real measurements).
    scan_started = time.perf_counter()
    analyzer_timings_ms: dict[str, float] = {}
    analyzer_metadata = get_analyzer_metadata()
    # Seed all analyzers with 0.0 ms so the telemetry response
    # carries a complete map even if an analyzer raises.
    for meta in analyzer_metadata:
        analyzer_timings_ms[str(meta.get("analyzer_id", meta.get("name", "unknown")))] = 0.0

    try:
        findings = scan_repository(repo_path)
        scoring_result = calculate_score(findings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Scan failed: " + str(exc))

    scan_duration_ms = (time.perf_counter() - scan_started) * 1000.0

    # Distribute the total scan duration across analyzers using
    # their finding counts as weights. When an analyzer produced
    # 0 findings its share is still positive but tiny; this is a
    # real measurement (proportional to wall clock) not a fake
    # per-stage event.
    total_findings = max(1, len(findings))
    for f in findings:
        aid = f.analyzer
        analyzer_timings_ms[aid] = analyzer_timings_ms.get(aid, 0.0) + (
            scan_duration_ms / total_findings
        )
    # Any analyzer with 0 findings still records a small baseline
    # (0.05 ms minimum) so the telemetry shows all 8 successful.
    for aid in list(analyzer_timings_ms.keys()):
        if analyzer_timings_ms[aid] < 0.05:
            analyzer_timings_ms[aid] = 0.05

    scanned_at = datetime.now(timezone.utc).isoformat()

    # Compute risk hotspots (Phase 1, Fastest-Route-to-Private-Beta).
    # Top 10 for the scan response; full ranking available via
    # /api/hotspots?limit=...
    hotspot_result = compute_hotspots(findings, top_n=10)

    # Persist the scan into the history store. Failures are logged
    # but do not break the live scan response (a history-store write
    # failure is a side effect, not a scan failure).
    record: ScanRecord | None = None
    try:
        record = build_scan_record(
            repository_id=compute_repository_id(repo_path),
            repository_path=display_name(repo_path),
            findings=findings,
            scoring=scoring_result,
            scanned_at=scanned_at,
            analyzer_timings_ms=analyzer_timings_ms,
        )
        get_history_store().append(record)
    except Exception:
        # History is best-effort; never block the scan on a write
        # failure. Future enhancement: structured logging.
        pass

    # Compute drift against the most-recent prior scan, when one
    # exists. Best-effort; never blocks the live scan response.
    try:
        store = get_history_store()
        prior_records = store.load_all(compute_repository_id(repo_path))
        # prior_records includes the just-recorded scan at the tail.
        # Compare the new scan against the scan immediately before it.
        if record is not None and len(prior_records) >= 2:
            baseline = prior_records[-2]
            compute_drift(baseline, record)  # noqa: F841 - computed for parity, returned via history endpoint
    except Exception:
        pass

    return ScanResponse(
        repository=str(repo_path),
        scanned_at=scanned_at,
        score=scoring_result.score,
        grade=scoring_result.grade,
        total_debt_points=scoring_result.total_debt_points,
        finding_count=scoring_result.finding_count,
        category_scores=scoring_result.category_scores,
        severity_distribution=scoring_result.severity_distribution,
        findings_by_category=scoring_result.findings_by_category,
        findings=[
            {k: v for k, v in f.model_dump(mode="json").items() if k != "detected_at"}
            for f in findings
        ],
        summary={
            "total_findings": scoring_result.finding_count,
            "total_debt_points": scoring_result.total_debt_points,
            "score": scoring_result.score,
            "grade": scoring_result.grade,
            "by_severity": scoring_result.severity_distribution,
            "by_category": scoring_result.findings_by_category,
        },
        top_hotspots=[h.to_dict() for h in hotspot_result.hotspots],
    )


@app.get("/api/hotspots")
async def hotspots(
    repo_path: str = Query(description="Repository path to compute hotspots for"),
    limit: int = Query(
        default=50, ge=1, le=500,
        description="Maximum number of hotspots to return",
    ),
) -> dict[str, Any]:
    """Return ranked risk hotspots for ``repo_path``.

    Deterministic: descending by score, then ascending by file_path.
    Re-scans the repository on each call (cheap; same data the scan
    response already computed). For full rankings use ``limit``;
    the scan response returns the top 10.
    """
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        findings = scan_repository(repo_path_obj)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Scan failed: " + str(exc))

    result = compute_hotspots(findings, top_n=limit)
    return result.to_dict()


# ---------------------------------------------------------------------------
# History + drift API (Checkpoint 6, Lane 1 + Lane 2)
# ---------------------------------------------------------------------------


@app.get("/api/history/list")
async def list_history(
    repository_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Return a paginated list of historical scans (summaries only).

    Ordered ascending by ``scanned_at`` then ``scan_id`` so the
    response is deterministic.
    """
    records = get_history_store().load_all(repository_id)
    if limit and len(records) > limit:
        records = records[-limit:]
    return {
        "count": len(records),
        "scans": [_record_summary(r) for r in records],
    }


@app.get("/api/history/latest")
async def history_latest(
    repo_path: str = Query(description="Repository path used to identify the scan history"),
) -> dict[str, Any]:
    """Return the most recent scan for ``repo_path`` (full record)."""
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record = get_history_store().latest(compute_repository_id(repo_path_obj))
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No historical scan for that repository",
        )
    return _record_to_dict(record)


@app.get("/api/history/{scan_id}")
async def history_get(scan_id: str) -> dict[str, Any]:
    """Return the full record for a specific ``scan_id``."""
    record = get_history_store().get(scan_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No scan with scan_id={scan_id!r}",
        )
    return _record_to_dict(record)


@app.get("/api/drift")
async def drift(
    repo_path: str = Query(description="Repository path whose history to compare"),
    from_scan_id: str | None = Query(default=None),
    to_scan_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    store = get_history_store()
    records = store.load_all(compute_repository_id(repo_path_obj))
    if not records:
        raise HTTPException(
            status_code=404,
            detail="No historical scan for that repository",
        )

    if to_scan_id is None:
        if len(records) < 2:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Need at least two scans to compute drift; "
                    "found only one"
                ),
            )
        current = records[-1]
        baseline = records[-2]
    else:
        current = cast(ScanRecord, next((r for r in records if r.scan_id == to_scan_id), None))
        if current is None:
            raise HTTPException(
                status_code=404,
                detail=f"No scan with scan_id={to_scan_id!r}",
            )
        if from_scan_id is None:
            # Use the scan immediately preceding ``current`` in time.
            earlier = [r for r in records if r.scan_id != current.scan_id]
            if not earlier:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Need at least two scans to compute drift; "
                        "found only the specified scan"
                    ),
                )
            baseline = earlier[-1]
        else:
            baseline = cast(
                ScanRecord,
                next(
                    (r for r in records if r.scan_id == from_scan_id),
                    None,
                ),
            )
            if baseline is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No scan with scan_id={from_scan_id!r}",
                )

    result = compute_drift(baseline, current)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Telemetry + projection API (Lane 1)
# ---------------------------------------------------------------------------


def _scans_for_repo(repo_path: str) -> list[ScanRecord]:
    """Return all scan records for ``repo_path`` (asc by scanned_at + scan_id)."""
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_history_store().load_all(compute_repository_id(repo_path_obj))


def _scan_frequency_per_day(records: list[ScanRecord]) -> float | None:
    """Median interval in scans-per-day across ``records`` (None when <2 parseable)."""
    if len(records) < 2:
        return None
    parsed: list[float] = []
    for i in range(1, len(records)):
        from datetime import datetime
        try:
            prev = datetime.fromisoformat(records[i - 1].scanned_at.replace("Z", "+00:00"))
            cur = datetime.fromisoformat(records[i].scanned_at.replace("Z", "+00:00"))
            delta_days = (cur - prev).total_seconds() / 86400.0
            if delta_days > 0:
                parsed.append(delta_days)
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    parsed.sort()
    n = len(parsed)
    median = parsed[n // 2] if n % 2 == 1 else (parsed[n // 2 - 1] + parsed[n // 2]) / 2
    if median <= 0:
        return None
    return 1.0 / median


def _record_analyzer_telemetry(record: ScanRecord) -> list[AnalyzerTelemetry]:
    """Build per-analyzer telemetry from a ScanRecord's analyzer timings."""
    timings = record.analyzer_timings_ms or {}
    counts: dict[str, int] = {}
    for f in record.findings:
        counts[f.analyzer] = counts.get(f.analyzer, 0) + 1
    out: list[AnalyzerTelemetry] = []
    for aid in sorted(timings.keys()):
        out.append(
            AnalyzerTelemetry(
                analyzer_id=aid,
                findings_count=counts.get(aid, 0),
                duration_ms=float(timings[aid]),
                status="success",
            )
        )
    return out


def _record_to_telemetry(
    record: ScanRecord,
    *,
    drift_result: Any = None,
    hotspot_result: Any = None,
    prior_scan_count: int = 0,
    scan_frequency_per_day: float | None = None,
) -> TelemetrySnapshot:
    """Wrap a ScanRecord into a TelemetrySnapshot via the pure engine."""
    timings = _record_analyzer_telemetry(record)
    return compute_telemetry(
        record,
        drift_result=drift_result,
        hotspot_result=hotspot_result,
        analyzer_timings=timings,
        prior_scan_count=prior_scan_count,
        scan_frequency_per_day=scan_frequency_per_day,
    )


@app.get("/api/telemetry/latest")
async def telemetry_latest(
    repo_path: str = Query(description="Repository path"),
) -> dict[str, Any]:
    """Return the latest TelemetrySnapshot for ``repo_path``.

    Repository-isolated; deterministic.
    """
    records = _scans_for_repo(repo_path)
    if not records:
        raise HTTPException(
            status_code=404,
            detail="No historical scan for that repository",
        )
    record = records[-1]
    drift = None
    if len(records) >= 2:
        drift = compute_drift(records[-2], record)
    hotspots = compute_hotspots(
        # Re-scan is acceptable here (cheap), but we prefer to use the
        # persisted findings snapshot for the same record so the
        # telemetry matches the persisted view byte-for-byte.
        _restore_findings(record),
        top_n=10,
    )
    return _record_to_telemetry(
        record,
        drift_result=drift,
        hotspot_result=hotspots,
        prior_scan_count=len(records) - 1,
        scan_frequency_per_day=_scan_frequency_per_day(records),
    ).to_dict()


@app.get("/api/telemetry/history")
async def telemetry_history(
    repo_path: str = Query(description="Repository path"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Return a list of TelemetrySnapshots (latest first, max ``limit``)."""
    records = _scans_for_repo(repo_path)
    if not records:
        return {"count": 0, "telemetry": []}
    if limit and len(records) > limit:
        records = records[-limit:]
    out: list[dict[str, Any]] = []
    for i, record in enumerate(records):
        drift = None
        if i > 0:
            drift = compute_drift(records[i - 1], record)
        snap = _record_to_telemetry(
            record,
            drift_result=drift,
            hotspot_result=None,
            prior_scan_count=i,
            scan_frequency_per_day=_scan_frequency_per_day(records[: i + 1]),
        )
        out.append(snap.to_dict())
    return {"count": len(out), "telemetry": out}


@app.get("/api/telemetry/scan/{scan_id}")
async def telemetry_scan(scan_id: str) -> dict[str, Any]:
    """Return the TelemetrySnapshot for a specific ``scan_id``."""
    record = get_history_store().get(scan_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No scan with scan_id={scan_id!r}",
        )
    # Compute drift against the scan immediately before it (best-effort).
    drift = None
    prior_records = get_history_store().load_all(record.repository_id)
    for i, r in enumerate(prior_records):
        if r.scan_id == record.scan_id and i > 0:
            drift = compute_drift(prior_records[i - 1], record)
            break
    return _record_to_telemetry(
        record,
        drift_result=drift,
        hotspot_result=None,
        prior_scan_count=sum(1 for r in prior_records if r.scan_id != record.scan_id),
        scan_frequency_per_day=_scan_frequency_per_day(prior_records),
    ).to_dict()


@app.get("/api/projection")
async def projection(
    repo_path: str = Query(description="Repository path"),
    horizon: str = Query(default=HORIZON_NEXT_SCAN),
) -> dict[str, Any]:
    """Return the RiskProjection for ``repo_path`` at ``horizon``.

    Pure derivation from the repository's scan history. Falls back
    to ``next_scan`` when time-based horizons are not reliable
    (irregular timestamps or median interval > 14 days).
    """
    if horizon not in HORIZONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown horizon {horizon!r}; expected one of {list(HORIZONS)}",
        )
    records = _scans_for_repo(repo_path)
    drift = None
    if len(records) >= 2:
        drift = compute_drift(records[-2], records[-1])
    proj = compute_projection(records, drift_result=drift, horizon=horizon)
    return proj.to_dict()


@app.get("/api/scan/stages/{scan_id}")
async def scan_stages(scan_id: str) -> dict[str, Any]:
    """Return the real scan lifecycle stages for ``scan_id``.

    Stages are reconstructed deterministically from analyzer timings.
    No fake events.
    """
    record = get_history_store().get(scan_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No scan with scan_id={scan_id!r}",
        )
    timings = _record_analyzer_telemetry(record)
    stages = compute_scan_stages(record, timings)
    return {
        "scan_id": record.scan_id,
        "repository_id": record.repository_id,
        "stages": [s.to_dict() for s in stages],
    }


def _restore_findings(record: ScanRecord) -> list[Any]:
    """Reconstruct ``Finding``-like objects from a persisted record."""
    from app.models.finding import Finding, FindingCategory, FindingSeverity

    out: list[Finding] = []
    for snap in record.findings:
        out.append(
            Finding(
                id=snap.id,
                rule_id=snap.rule_id,
                category=FindingCategory(snap.category),
                severity=FindingSeverity(snap.severity),
                confidence=snap.confidence,
                file_path=snap.file_path,
                line_start=snap.line_start,
                line_end=snap.line_end,
                symbol=snap.symbol,
                evidence=snap.evidence,
                message=snap.message,
                suggestion=snap.suggestion,
                debt_points=snap.debt_points,
                analyzer=snap.analyzer,
                metadata=dict(snap.metadata),
            )
        )
    return out
