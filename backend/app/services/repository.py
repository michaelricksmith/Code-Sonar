"""Repository scanning service. Orchestrates analyzers with security gates."""

from __future__ import annotations

from pathlib import Path

from app.analyzers.base import Analyzer
from app.analyzers.comment_markers import CommentMarkersAnalyzer
from app.analyzers.cyclomatic_complexity import CyclomaticComplexityAnalyzer
from app.analyzers.dead_code import DeadCodeAnalyzer
from app.analyzers.nesting_depth import NestingDepthAnalyzer
from app.analyzers.oversized_files import OversizedFilesAnalyzer
from app.analyzers.oversized_functions import OversizedFunctionsAnalyzer
from app.analyzers.secrets import SecretsAnalyzer
from app.analyzers.testing_debt import TestingDebtAnalyzer
from app.models.finding import Finding
from app.security import (
    assert_within_scan_limits,
    is_safe_to_read,
    redact_secrets,
    truncate_evidence,
    validate_repo_path,
)


def get_registered_analyzers() -> list[Analyzer]:
    """Return analyzers in deterministic execution order."""
    return [
        CommentMarkersAnalyzer(),
        OversizedFilesAnalyzer(),
        OversizedFunctionsAnalyzer(),
        CyclomaticComplexityAnalyzer(),
        NestingDepthAnalyzer(),
        SecretsAnalyzer(),
        TestingDebtAnalyzer(),
        DeadCodeAnalyzer(),
    ]


def get_analyzer_metadata() -> list[dict[str, object]]:
    return [
        {
            "name": analyzer.name,
            "analyzer_id": analyzer.name,
            "category": "general",
            "threshold": getattr(analyzer, "threshold", None),
        }
        for analyzer in get_registered_analyzers()
    ]


def _finding_is_scannable(finding: Finding, repo_path: Path) -> bool:
    """Keep only findings attached to files that pass the repository read policy.

    Analyzers currently perform their own filesystem walks. This service-level
    gate guarantees generated/runtime artifacts cannot leak into the canonical
    finding set even if an individual analyzer sees them during its walk.
    """
    raw = finding.file_path.replace("\\", "/")
    candidate = repo_path.joinpath(*[part for part in raw.split("/") if part])
    return candidate.is_file() and is_safe_to_read(candidate, repo_path)


def _scan_path(repo_path: Path) -> list[Finding]:
    """Run analyzers and return the canonical, security-filtered finding set."""
    file_count = 0
    total_size = 0
    for path in repo_path.rglob("*"):
        if not path.is_file() or not is_safe_to_read(path, repo_path):
            continue
        try:
            total_size += path.stat().st_size
        except OSError:
            continue
        file_count += 1
        assert_within_scan_limits(file_count, total_size)

    findings: list[Finding] = []
    for analyzer in get_registered_analyzers():
        try:
            produced = analyzer.analyze(repo_path)
        except Exception:
            continue
        for finding in produced:
            if not _finding_is_scannable(finding, repo_path):
                continue
            finding.evidence = truncate_evidence(redact_secrets(finding.evidence or ""))
            findings.append(finding)
    return findings


def scan_repository(repo_path: object) -> list[Finding]:
    """Validate, scan, and return aggregated canonical findings."""
    resolved = validate_repo_path(repo_path)
    return _scan_path(resolved)
