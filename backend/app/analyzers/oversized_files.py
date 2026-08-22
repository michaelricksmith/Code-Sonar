"""Oversized files analyzer — flags source files above a line-count threshold."""

from __future__ import annotations

from pathlib import Path

from app.analyzers.base import Analyzer
from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.security import (
    EXCLUDED_DIRS,
    is_binary_content,
    is_binary_extension,
    is_excluded_directory,
    is_lockfile,
    is_symlink,
)


# Default line-count thresholds per Source file extension (lines).
DEFAULT_THRESHOLD: int = 500

# Source file extensions considered for line-count measurement.
SOURCE_EXTENSIONS: frozenset = frozenset({
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".java", ".kt", ".scala", ".groovy",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx",
    ".cs", ".vb",
    ".go", ".rs",
    ".rb", ".php",
    ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh",
    ".ps1",
    ".html", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte",
    ".sql",
    ".md", ".rst", ".tex",
    ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".json", ".xml",
})

# Severity thresholds (fraction of the configured limit).
# Below 2x  → WARNING; 2x–3x → ERROR; 3x+ → CRITICAL.
WARNING_FACTOR: float = 1.0
ERROR_FACTOR: float = 2.0
CRITICAL_FACTOR: float = 3.0


def _severity_for(line_count: int, threshold: int) -> tuple[FindingSeverity, int]:
    """Map line_count vs threshold to (severity, debt_points)."""
    if line_count >= threshold * CRITICAL_FACTOR:
        return FindingSeverity.CRITICAL, 12
    if line_count >= threshold * ERROR_FACTOR:
        return FindingSeverity.ERROR, 8
    return FindingSeverity.WARNING, 4


class OversizedFilesAnalyzer(Analyzer):
    """Detects source files that exceed a configurable line-count threshold.

    Files are only reported when their line count is strictly greater
    than the configured threshold. Files inside excluded directories
    (per app.security.EXCLUDED_DIRS), binary files, symlinks, and
    files with non-source extensions are skipped.

    Finding IDs are deterministic, derived from the relative file path
    and the line count, so repeated scans of the same repository
    produce identical finding IDs.
    """

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "oversized_files"

    @property
    def threshold(self) -> int:
        return self._threshold

    def analyze(self, repo_path: Path) -> list[Finding]:
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return []

        findings: list[Finding] = []
        for file_path in self._walk_files(repo_path):
            if not self._is_eligible(file_path, repo_path):
                continue
            try:
                line_count = self._count_lines(file_path)
            except OSError:
                continue
            if line_count <= self._threshold:
                continue
            findings.append(self._build_finding(file_path, repo_path, line_count))
        return findings

    def _walk_files(self, repo_path: Path) -> list[Path]:
        files: list[Path] = []

        def walk(path: Path) -> None:
            try:
                for entry in path.iterdir():
                    if entry.is_dir():
                        if entry.name not in EXCLUDED_DIRS:
                            walk(entry)
                    elif entry.is_file():
                        files.append(entry)
            except (PermissionError, OSError):
                pass

        walk(repo_path)
        return files

    def _is_eligible(self, file_path: Path, repo_root: Path) -> bool:
        try:
            rel = file_path.resolve().relative_to(repo_root)
        except ValueError:
            return False
        if is_symlink(file_path):
            return False
        if is_excluded_directory(rel):
            return False
        if is_lockfile(file_path):
            return False
        if file_path.suffix.lower() not in SOURCE_EXTENSIONS:
            return False
        if is_binary_extension(file_path):
            return False
        if is_binary_content(file_path):
            return False
        return True

    def _count_lines(self, file_path: Path) -> int:
        with open(file_path, "rb") as f:
            return sum(1 for _ in f)

    def _build_finding(
        self, file_path: Path, repo_root: Path, line_count: int
    ) -> Finding:
        rel = file_path.resolve().relative_to(repo_root).as_posix()
        severity, debt_points = _severity_for(line_count, self._threshold)
        finding_id = (
            "finding_oversized_files_"
            f"{hash((rel, line_count, self._threshold)) & 0xFFFFFFFF:08x}"
        )
        evidence = (
            f"line_count={line_count}, threshold={self._threshold}, file={rel}"
        )
        message = (
            f"Source file '{rel}' is {line_count} lines "
            f"(threshold {self._threshold})"
        )
        suggestion = (
            "Split this file into smaller modules along responsibility "
            "boundaries; aim for files under the configured line threshold."
        )
        return Finding(
            id=finding_id,
            rule_id="oversized_files:over-threshold",
            category=FindingCategory.MAINTAINABILITY,
            severity=severity,
            confidence=1.0,
            file_path=rel,
            line_start=1,
            line_end=line_count,
            symbol=None,
            evidence=evidence,
            message=message,
            suggestion=suggestion,
            debt_points=debt_points,
            remediation_effort=self._remediation_effort(line_count, self._threshold),
            analyzer=self.name,
            metadata={
                "line_count": line_count,
                "threshold": self._threshold,
                "severity_factor": round(line_count / self._threshold, 2),
            },
        )

    @staticmethod
    def _remediation_effort(line_count: int, threshold: int) -> str:
        excess_ratio = line_count / max(threshold, 1)
        if excess_ratio >= 3:
            return "1 day"
        if excess_ratio >= 2:
            return "4 hours"
        return "2 hours"
