"""FastAPI application entry point."""

from datetime import datetime, timezone
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.ask_sonar.api import router as ask_sonar_router
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
from app.ml.api import router as ml_router
from app.scoring.engine import calculate_score
from app.security import RepositoryValidationError, validate_repo_path
from app.services.repository import (
    get_analyzer_metadata,
    get_registered_analyzers,
    scan_repository,
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
app.include_router(ml_router)
app.include_router(ask_sonar_router)


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

    try:
        findings = scan_repository(repo_path)
        scoring_result = calculate_score(findings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Scan failed: " + str(exc))

    scanned_at = datetime.now(timezone.utc).isoformat()

    # Compute risk hotspots (Phase 1, Fastest-Route-to-Private-Beta).
    # Top 10 for the scan response; full ranking available via
    # /api/hotspots?limit=...
    hotspot_result = compute_hotspots(findings, top_n=10)

    # Persist the scan into the history store. Failures are logged
    # but do not break the live scan response (a history-store write
    # failure is a side effect, not a scan failure).
    try:
        record = build_scan_record(
            repository_id=compute_repository_id(repo_path),
            repository_path=display_name(repo_path),
            findings=findings,
            scoring=scoring_result,
            scanned_at=scanned_at,
        )
        get_history_store().append(record)
    except Exception:
        # History is best-effort; never block the scan on a write
        # failure. Future enhancement: structured logging.
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
        default=50,
        ge=1,
        le=500,
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
    """Compute drift between two historical scans of ``repo_path``.

    Defaults: ``from_scan_id`` = second-most-recent, ``to_scan_id`` =
    most-recent. Returns the full DriftResult (aggregate summary +
    per-finding classifications + drill-downs by category, analyzer,
    and severity).
    """
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
