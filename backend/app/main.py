"""FastAPI application entry point."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.scoring.engine import calculate_score
from app.security import RepositoryValidationError, validate_repo_path
from app.services.repository import scan_repository


app = FastAPI(
    title="Code Sonar API",
    description="Credit report for your codebase",
    version="0.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Code Sonar API", "version": "0.1.0"}


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
    )