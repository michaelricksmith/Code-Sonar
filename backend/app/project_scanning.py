"""Shared deterministic project scan workflow for API and webhook-triggered scans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.history import ScanRecord, build_scan_record, compute_repository_id, display_name
from app.history_runtime import get_history_store
from app.models.finding import Finding
from app.projects import ProjectRecord, get_project_store
from app.scoring.engine import ScoringResult, calculate_score
from app.security import validate_repo_path
from app.services.repository import scan_repository


@dataclass(frozen=True, slots=True)
class ProjectScanOutcome:
    project: ProjectRecord
    record: ScanRecord
    findings: list[Finding]
    scoring: ScoringResult


def scan_project(project_id: str) -> ProjectScanOutcome:
    """Run, score, persist, and bind a scan to an existing Code Sonar project."""
    project = get_project_store().get(project_id)
    if project is None:
        raise LookupError("Project not found")

    repo_path = validate_repo_path(project.local_checkout_path)
    findings = scan_repository(repo_path)
    scoring = calculate_score(findings)
    scanned_at = datetime.now(timezone.utc).isoformat()
    record = build_scan_record(
        repository_id=compute_repository_id(repo_path),
        repository_path=display_name(repo_path),
        findings=findings,
        scoring=scoring,
        scanned_at=scanned_at,
    )
    get_history_store().append(record)
    updated_project = get_project_store().record_scan(
        project_id,
        scan_id=record.scan_id,
        score=record.score,
    )
    return ProjectScanOutcome(
        project=updated_project,
        record=record,
        findings=findings,
        scoring=scoring,
    )
