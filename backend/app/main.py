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
from app.remediation.api import router as remediation_router
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
app.include_router(remediation_router)


_history_store: JsonlHistoryStore | InMemoryHistoryStore = JsonlHistoryStore()


def get_history_store() -> JsonlHistoryStore | InMemoryHistoryStore:
    return _history_store


def set_history_store(store: JsonlHistoryStore | InMemoryHistoryStore) -> None:
    global _history_store
    _history_store = store


class ScanRequest(BaseModel):
    repo_path: str = Field(description="Path to repository root directory")


class ScanResponse(BaseModel):
    repository: str
    scan_id: str | None = None
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
    top_hotspots: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Code Sonar API", "version": "0.1.0"}


@app.get("/api/analyzers")
async def list_analyzers() -> dict[str, Any]:
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
    hotspot_result = compute_hotspots(findings, top_n=10)

    persisted_scan_id: str | None = None
    try:
        record = build_scan_record(
            repository_id=compute_repository_id(repo_path),
            repository_path=display_name(repo_path),
            findings=findings,
            scoring=scoring_result,
            scanned_at=scanned_at,
        )
        get_history_store().append(record)
        persisted_scan_id = record.scan_id
    except Exception:
        pass

    return ScanResponse(
        repository=str(repo_path),
        scan_id=persisted_scan_id,
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
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
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


@app.get("/api/history/list")
async def list_history(
    repository_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    records = get_history_store().list(repository_id=repository_id, limit=limit)
    return {"count": len(records), "scans": [_record_summary(r) for r in records]}


@app.get("/api/history/latest")
async def latest_history(repo_path: str = Query(description="Repository path")) -> dict[str, Any]:
    try:
        repo = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    repo_id = compute_repository_id(repo)
    record = get_history_store().latest(repository_id=repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No scan history found for repository")
    return _record_to_dict(record)


@app.get("/api/history/{scan_id}")
async def history_by_id(scan_id: str) -> dict[str, Any]:
    record = get_history_store().get(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _record_to_dict(record)


@app.get("/api/drift")
async def drift(
    repo_path: str = Query(description="Repository path"),
    from_scan_id: str | None = Query(default=None),
    to_scan_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        repo = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    repository_id = compute_repository_id(repo)
    store = get_history_store()

    if from_scan_id and to_scan_id:
        baseline = store.get(from_scan_id)
        current = store.get(to_scan_id)
    else:
        history = store.list(repository_id=repository_id, limit=2)
        if len(history) < 2:
            raise HTTPException(status_code=404, detail="Need at least two scans")
        current, baseline = history[0], history[1]

    if baseline is None or current is None:
        raise HTTPException(status_code=404, detail="Requested scan not found")
    if baseline.repository_id != repository_id or current.repository_id != repository_id:
        raise HTTPException(status_code=400, detail="Scan does not belong to repository")

    return cast(dict[str, Any], compute_drift(baseline, current).to_dict())
