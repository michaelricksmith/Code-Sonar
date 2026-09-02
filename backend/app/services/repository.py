"""Repository scanning service. Orchestrates analyzers with security gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence, overload

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


@dataclass(frozen=True)
class AnalyzerExecutionStatus:
    analyzer: str
    status: str
    finding_count: int
    error_type: str | None = None


@dataclass(frozen=True)
class ScanExecutionResult(Sequence[Finding]):
    """Canonical findings plus explicit analyzer-completeness evidence."""

    findings: tuple[Finding, ...]
    analyzers: tuple[AnalyzerExecutionStatus, ...]

    @property
    def complete(self) -> bool:
        return bool(self.analyzers) and all(
            item.status == "completed" for item in self.analyzers
        )

    @overload
    def __getitem__(self, index: int) -> Finding: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Finding, ...]: ...

    def __getitem__(self, index: int | slice) -> Finding | tuple[Finding, ...]:
        return self.findings[index]

    def __len__(self) -> int:
        return len(self.findings)

    def __iter__(self) -> Iterator[Finding]:
        return iter(self.findings)


def _scan_path(repo_path: Path) -> ScanExecutionResult:
    """Run analyzers and return findings with explicit execution status."""
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
    statuses: list[AnalyzerExecutionStatus] = []
    for analyzer in get_registered_analyzers():
        try:
            produced = analyzer.analyze(repo_path)
        except Exception as exc:
            statuses.append(
                AnalyzerExecutionStatus(
                    analyzer=analyzer.name,
                    status="failed",
                    finding_count=0,
                    error_type=type(exc).__name__,
                )
            )
            continue
        accepted = 0
        for finding in produced:
            if not _finding_is_scannable(finding, repo_path):
                continue
            finding.evidence = truncate_evidence(redact_secrets(finding.evidence or ""))
            findings.append(finding)
            accepted += 1
        statuses.append(
            AnalyzerExecutionStatus(
                analyzer=analyzer.name,
                status="completed",
                finding_count=accepted,
            )
        )
    return ScanExecutionResult(tuple(findings), tuple(statuses))


def scan_repository(repo_path: object) -> ScanExecutionResult:
    """Validate, scan, and return findings plus analyzer completeness."""
    resolved = validate_repo_path(repo_path)
    return _scan_path(resolved)
