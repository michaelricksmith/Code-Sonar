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
    """Return all analyzers eligible to run against the target repository.

    Order is preserved for deterministic output: analyzers run in the
    order they appear here, and finding IDs are stable across runs.
    """
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
    """Return public metadata for every registered analyzer.

    Consumers (UI, CI, integrations) can introspect the analyzer
    pipeline without importing analyzer modules directly.
    """
    return [
        {
            "name": analyzer.name,
            "analyzer_id": analyzer.name,
            "category": "general",
            "threshold": getattr(analyzer, "threshold", None),
        }
        for analyzer in get_registered_analyzers()
    ]


def _scan_path(repo_path: Path) -> list[Finding]:
    """Run all analyzers against an already-validated repo path.

    The analyzers themselves do their own file walks; the service is
    responsible only for: (1) calling each analyzer, (2) enforcing the
    file-count/size caps, (3) redaction and truncation of evidence.
    """
    file_count = 0
    total_size = 0
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if not is_safe_to_read(path, repo_path):
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
            finding.evidence = truncate_evidence(redact_secrets(finding.evidence or ""))
            findings.append(finding)
    return findings


def scan_repository(repo_path: object) -> list[Finding]:
    """Validate, scan, and return aggregated findings from all analyzers."""
    resolved = validate_repo_path(repo_path)
    return _scan_path(resolved)
