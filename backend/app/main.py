"""FastAPI application entry point."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.ask_sonar.api import router as ask_sonar_router
from app.drift import compute_drift
from app.github_app import router as github_app_router
from app.github_app import set_webhook_scan_handler
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
from app.oauth import router as oauth_router
from app.persistence.privacy_api import router as privacy_router
from app.projects import get_project_store
from app.projects import router as projects_router
from app.readiness_api import router as readiness_router
from app.remediation.api import router as remediation_router
from app.scan_jobs import router as scan_job_router
from app.scoring.engine import SCORING_VERSION, calculate_score
from app.security import RepositoryValidationError, validate_repo_path
from app.security.runtime import ApiBoundaryMiddleware, validate_runtime_security_config
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

app.add_middleware(ApiBoundaryMiddleware)


@app.on_event("startup")
async def validate_security_configuration() -> None:
    """Fail closed before serving when authentication or CORS is unsafe."""
    validate_runtime_security_config()
    from app.persistence import configure_persistence_from_env

    configure_persistence_from_env()


app.include_router(ml_router)
app.include_router(ask_sonar_router)
app.include_router(oauth_router)
app.include_router(scan_job_router)
app.include_router(remediation_router)
app.include_router(projects_router)
app.include_router(github_app_router)
app.include_router(privacy_router)
app.include_router(readiness_router)

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
    scan_id: str | None = None
    scanned_at: str
    score: int
    grade: str
    scoring_version: str
    analyzer_execution: list[dict[str, Any]]
    total_debt_points: int
    finding_count: int
    category_scores: dict[str, int]
    severity_distribution: dict[str, int]
    findings_by_category: dict[str, int]
    penalty_explanation: dict[str, Any]
    findings: list[dict[str, Any]]
    summary: dict[str, Any]
    top_hotspots: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Directory holding the built dashboard SPA (`npm run build` in frontend/).
# Resolved against the process working directory so it works both from a repo
# checkout and from an installed package. When absent (local dev), the API
# behaves exactly as before and the Vite dev server serves the UI.
FRONTEND_DIST = Path(os.environ.get("CODESONAR_FRONTEND_DIST", "frontend/dist")).resolve()


@app.get("/")
async def root() -> Any:
    """Serve the dashboard SPA when built; otherwise the plain API greeting."""
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
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
        "scoring_version": record.scoring_version,
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


def _record_public_dict(record: ScanRecord) -> dict[str, Any]:
    data = _record_to_dict(record)
    data.pop("repository_path", None)
    return data


def _record_summary(record: ScanRecord) -> dict[str, Any]:
    return {
        "scan_id": record.scan_id,
        "repository_id": record.repository_id,
        "repository_path": record.repository_path,
        "scanned_at": record.scanned_at,
        "schema_version": record.schema_version,
        "scoring_version": record.scoring_version,
        "score": record.score,
        "grade": record.grade,
        "total_debt_points": record.total_debt_points,
        "finding_count": record.finding_count,
        "category_scores": record.category_scores,
        "severity_distribution": record.severity_distribution,
        "findings_by_category": record.findings_by_category,
        "findings_source_breakdown": record.findings_source_breakdown,
    }


def _record_public_summary(record: ScanRecord) -> dict[str, Any]:
    data = _record_summary(record)
    data.pop("repository_path", None)
    return data


def _build_scan_response(
    *,
    repository_label: str,
    findings: list[Any],
    scoring_result: Any,
    scanned_at: str,
    scan_id: str | None,
    analyzer_execution: list[dict[str, Any]],
) -> ScanResponse:
    hotspot_result = compute_hotspots(findings, top_n=10)
    return ScanResponse(
        repository=repository_label,
        scan_id=scan_id,
        scanned_at=scanned_at,
        score=scoring_result.score,
        grade=scoring_result.grade,
        scoring_version=SCORING_VERSION,
        analyzer_execution=analyzer_execution,
        total_debt_points=scoring_result.total_debt_points,
        finding_count=scoring_result.finding_count,
        category_scores=scoring_result.category_scores,
        severity_distribution=scoring_result.severity_distribution,
        findings_by_category=scoring_result.findings_by_category,
        penalty_explanation=scoring_result.penalty_explanation,
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


@app.post("/api/scan", response_model=ScanResponse)
async def scan(request: ScanRequest) -> ScanResponse:
    try:
        repo_path = validate_repo_path(request.repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        execution = scan_repository(repo_path)
        if not execution.complete:
            failures = [item.analyzer for item in execution.analyzers if item.status == "failed"]
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Scan incomplete; no authoritative score was produced",
                    "failed_analyzers": failures,
                },
            )
        findings = list(execution.findings)
        scoring_result = calculate_score(findings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Scan failed: " + str(exc)) from exc

    scanned_at = datetime.now(timezone.utc).isoformat()
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

    return _build_scan_response(
        repository_label=repo_path.name,
        findings=findings,
        scoring_result=scoring_result,
        scanned_at=scanned_at,
        scan_id=persisted_scan_id,
        analyzer_execution=[item.__dict__ for item in execution.analyzers],
    )


@app.post("/api/projects/{project_id}/scan", response_model=ScanResponse)
async def scan_project(project_id: str) -> ScanResponse:
    project = get_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        repo_path = validate_repo_path(project.local_checkout_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=409, detail="Project checkout is unavailable") from exc

    try:
        execution = scan_repository(repo_path)
        if not execution.complete:
            failures = [item.analyzer for item in execution.analyzers if item.status == "failed"]
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Project scan incomplete; no authoritative score was produced",
                    "failed_analyzers": failures,
                },
            )
        findings = list(execution.findings)
        scoring_result = calculate_score(findings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Project scan failed") from exc

    scanned_at = datetime.now(timezone.utc).isoformat()
    record = build_scan_record(
        repository_id=compute_repository_id(repo_path),
        repository_path=display_name(repo_path),
        findings=findings,
        scoring=scoring_result,
        scanned_at=scanned_at,
    )
    from app.persistence.runtime import record_project_scan_atomically

    record_project_scan_atomically(
        project_id,
        record,
        history_store=get_history_store(),
        project_store=get_project_store(),
    )

    return _build_scan_response(
        repository_label=f"{project.owner}/{project.name}",
        findings=findings,
        scoring_result=scoring_result,
        scanned_at=scanned_at,
        scan_id=record.scan_id,
        analyzer_execution=[item.__dict__ for item in execution.analyzers],
    )


set_webhook_scan_handler(scan_project)


@app.get("/api/projects/{project_id}/dashboard")
async def project_dashboard(project_id: str) -> dict[str, Any]:
    project = get_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    repository_id = compute_repository_id(Path(project.local_checkout_path))
    records = get_history_store().load_all(repository_id)
    latest = records[-1] if records else None
    return {
        "project": project.to_public_dict(),
        "latest_scan": _record_public_dict(latest) if latest else None,
        "history": [_record_public_summary(item) for item in records[-20:]],
        "history_count": len(records),
        "local_checkout_path_exposed": False,
        "deterministic_score_authority": "code_sonar",
    }


@app.get("/api/projects/{project_id}/drift")
async def project_drift(project_id: str) -> dict[str, Any]:
    project = get_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    repository_id = compute_repository_id(Path(project.local_checkout_path))
    records = get_history_store().load_all(repository_id)
    if len(records) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least two project scans to compute drift",
        )
    return compute_drift(records[-2], records[-1]).to_dict()


@app.get("/api/hotspots")
async def hotspots(
    repo_path: str = Query(description="Repository path to compute hotspots for"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        execution = scan_repository(repo_path_obj)
        if not execution.complete:
            raise HTTPException(status_code=503, detail="Scan incomplete")
        findings = list(execution.findings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Scan failed: " + str(exc)) from exc
    return compute_hotspots(findings, top_n=limit).to_dict()


@app.get("/api/history/list")
async def list_history(
    repository_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    records = get_history_store().load_all(repository_id)
    if limit and len(records) > limit:
        records = records[-limit:]
    return {"count": len(records), "scans": [_record_public_summary(r) for r in records]}


@app.get("/api/history/latest")
async def history_latest(
    repo_path: str = Query(description="Repository path used to identify the scan history"),
) -> dict[str, Any]:
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = get_history_store().latest(compute_repository_id(repo_path_obj))
    if record is None:
        raise HTTPException(status_code=404, detail="No historical scan for that repository")
    return _record_public_dict(record)


@app.get("/api/history/{scan_id}")
async def history_get(scan_id: str) -> dict[str, Any]:
    record = get_history_store().get(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No scan with scan_id={scan_id!r}")
    return _record_public_dict(record)


@app.get("/api/drift")
async def drift(
    repo_path: str = Query(description="Repository path whose history to compare"),
    from_scan_id: str | None = Query(default=None),
    to_scan_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        repo_path_obj = validate_repo_path(repo_path)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store = get_history_store()
    records = store.load_all(compute_repository_id(repo_path_obj))
    if not records:
        raise HTTPException(status_code=404, detail="No historical scan for that repository")

    if to_scan_id is None:
        if len(records) < 2:
            raise HTTPException(
                status_code=400,
                detail="Need at least two scans to compute drift; found only one",
            )
        current = records[-1]
        baseline = records[-2]
    else:
        current = cast(ScanRecord, next((r for r in records if r.scan_id == to_scan_id), None))
        if current is None:
            raise HTTPException(status_code=404, detail=f"No scan with scan_id={to_scan_id!r}")
        if from_scan_id is None:
            earlier = [r for r in records if r.scan_id != current.scan_id]
            if not earlier:
                raise HTTPException(
                    status_code=400,
                    detail="Need at least two scans to compute drift",
                )
            baseline = earlier[-1]
        else:
            baseline = cast(
                ScanRecord,
                next((r for r in records if r.scan_id == from_scan_id), None),
            )
            if baseline is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No scan with scan_id={from_scan_id!r}",
                )

    return compute_drift(baseline, current).to_dict()


if (FRONTEND_DIST / "index.html").is_file():
    # Serve the dashboard SPA (and its assets) from the same origin as the API,
    # so the UI's relative "/api" calls work with no CORS configuration.
    # Registered last so every /api/* route, /health, and /docs takes
    # precedence; html=True falls back to index.html for client-side
    # routes like /app.
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
