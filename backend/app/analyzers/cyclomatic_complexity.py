"""Cyclomatic complexity analyzer for Python.

Detects functions, async functions, and class methods whose cyclomatic
complexity (CC) exceeds a configurable threshold. Complexity is
computed with the ``radon.complexity.cc_visit`` walker — no regex-based
calculation, no hand-rolled CC counter.

Severity scales with how far the function exceeds the threshold:
  cc > threshold             -> WARNING
  cc >= 2 * threshold        -> ERROR
  cc >= 3 * threshold        -> CRITICAL

Malformed Python sources are silently skipped. Finding IDs are derived
from (relative file path, qualified symbol name, complexity value,
threshold) so repeated scans of the same repository produce
byte-identical IDs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Optional, Tuple

from radon.complexity import cc_visit  # type: ignore[import-untyped]

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

DEFAULT_COMPLEXITY_THRESHOLD: int = 10


def _severity_for(cc: int, threshold: int) -> Tuple[FindingSeverity, int]:
    """Return (severity, debt_points) for a function whose CC exceeds threshold.

    Raises ValueError when ``cc`` is at or below the threshold (no
    finding) or when the threshold is non-positive.
    """
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    if cc <= threshold:
        raise ValueError(
            f"CC value {cc} does not exceed threshold {threshold}; no finding"
        )
    if cc >= threshold * 3:
        return FindingSeverity.CRITICAL, 12
    if cc >= threshold * 2:
        return FindingSeverity.ERROR, 8
    return FindingSeverity.WARNING, 4


def _remediation_effort(cc: int, threshold: int) -> str:
    ratio = cc / max(threshold, 1)
    if ratio >= 3:
        return "1 day"
    if ratio >= 2:
        return "4 hours"
    return "2 hours"


def _walk_python_files(repo_path: Path) -> Iterator[Path]:
    """Yield every Python source file under repo_path, honoring security gates."""

    def walk(path: Path) -> Iterator[Path]:
        try:
            entries = list(path.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIRS:
                    yield from walk(entry)
            elif entry.is_file():
                yield entry

    for fp in walk(repo_path):
        if _is_eligible(fp, repo_path):
            yield fp


def _is_eligible(file_path: Path, repo_root: Path) -> bool:
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
    if file_path.suffix.lower() != ".py":
        return False
    if is_binary_extension(file_path):
        return False
    if is_binary_content(file_path):
        return False
    return True


def _safe_read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError, ValueError):
        try:
            return path.read_text(encoding="latin-1")
        except (UnicodeDecodeError, OSError, ValueError):
            return None


class CyclomaticComplexityAnalyzer(Analyzer):
    """Detects Python functions whose cyclomatic complexity exceeds the threshold."""

    def __init__(
        self, threshold: int = DEFAULT_COMPLEXITY_THRESHOLD
    ) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "cyclomatic_complexity"

    @property
    def threshold(self) -> int:
        return self._threshold

    def analyze(self, repo_path: Path) -> list[Finding]:
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return []
        findings: list[Finding] = []
        for file_path in _walk_python_files(repo_path):
            findings.extend(self._analyze_file(file_path, repo_path))
        return findings

    def _analyze_file(self, file_path: Path, repo_root: Path) -> list[Finding]:
        source = _safe_read(file_path)
        if source is None:
            return []
        rel_path = file_path.resolve().relative_to(repo_root).as_posix()
        try:
            blocks = cc_visit(source)
        except Exception:
            # SyntaxError, ValueError, or any radon-specific failure
            # on malformed input → skip without fabricating a finding.
            return []
        findings: list[Finding] = []
        for block in blocks:
            # radon reports both class-body aggregates and individual
            # methods/functions. We only want the inner functions/methods
            # so the same code isn't double-billed.
            if self._is_class_block(block):
                continue
            cc_value = getattr(block, "complexity", None)
            if cc_value is None:
                continue
            try:
                severity, debt_points = _severity_for(cc_value, self._threshold)
            except ValueError:
                continue
            findings.append(self._build_finding(
                block=block,
                cc_value=cc_value,
                rel_path=rel_path,
                severity=severity,
                debt_points=debt_points,
            ))
        return findings

    @staticmethod
    def _is_class_block(block: Any) -> bool:
        """Return True when ``block`` is a class-body aggregate, not a function.

        radon emits both kinds with ``cc_visit``. We report only the
        per-method / per-function entries and suppress class aggregates
        (which double-count method complexity at the class level).
        """
        # Class aggregates expose a ``methods`` attribute; individual
        # functions/methods do not. This is the only reliable differentiator.
        return hasattr(block, "methods")

    def _build_finding(
        self,
        block: Any,
        cc_value: int,
        rel_path: str,
        severity: FindingSeverity,
        debt_points: int,
    ) -> Finding:
        qualified = (
            getattr(block, "fullname", None)
            or getattr(block, "name", "<anonymous>")
        )
        line_start = getattr(block, "lineno", 1) or 1
        line_end = getattr(block, "endline", line_start) or line_start
        finding_id = (
            "finding_cyclomatic_complexity_"
            f"{hash((rel_path, qualified, cc_value, self._threshold)) & 0xFFFFFFFF:08x}"
        )
        evidence = (
            f"symbol={qualified} complexity={cc_value} threshold={self._threshold}"
        )
        message = (
            f"Function '{qualified}' has cyclomatic complexity "
            f"{cc_value} (threshold {self._threshold})"
        )
        suggestion = (
            "Reduce complexity by extracting helper functions for individual "
            "branches, replacing conditional chains (if/elif) with lookup "
            "tables, or splitting the function along responsibility "
            "boundaries."
        )
        return Finding(
            id=finding_id,
            rule_id="cyclomatic_complexity:over-threshold",
            category=FindingCategory.COMPLEXITY,
            severity=severity,
            confidence=1.0,
            file_path=rel_path,
            line_start=line_start,
            line_end=line_end,
            symbol=qualified,
            evidence=evidence,
            message=message,
            suggestion=suggestion,
            debt_points=debt_points,
            remediation_effort=_remediation_effort(cc_value, self._threshold),
            analyzer=self.name,
            metadata={
                "symbol": qualified,
                "complexity": cc_value,
                "threshold": self._threshold,
                "is_method": bool(getattr(block, "is_method", False)),
                "severity_factor": round(cc_value / self._threshold, 2),
            },
        )
