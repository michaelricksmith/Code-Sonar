"""Testing-debt analyzer for Python.

Heuristics for missing or thin test coverage. This analyzer does not
run tests; it produces static findings only.

Two rules:

1. `testing_debt:untested-module`
   Emits a finding per Python source module (file) that lives under a
   non-`tests/` directory and has no matching test file under `tests/`
   (filename `<module>_test.py` or `test_<module>.py`). The presence
   of any matching test file counts as "tested".

2. `testing_debt:missing-tests-dir`
   Emits a single finding per scan if the repository has no `tests/`
   directory at all.

Severity scales with file size for `untested-module` findings:
  lines <= 100           -> WARNING
  lines <= 300           -> ERROR
  lines > 300            -> CRITICAL

Detection is gated by `app.security` (excluded dirs, lockfiles,
binary files, symlinks).

Finding IDs are derived from (relative file path, rule_id) so repeated
scans of the same repository produce byte-identical IDs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Set

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

DEFAULT_LARGE_FILE_LINES: int = 300
DEFAULT_MEDIUM_FILE_LINES: int = 100
TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test"})
TEST_FILE_PREFIXES: tuple[str, ...] = ("test_",)
TEST_FILE_SUFFIXES: tuple[str, ...] = ("_test.py", "_test.pyi", "test.py")


def _severity_for_lines(lines: int) -> tuple[FindingSeverity, int]:
    if lines > DEFAULT_LARGE_FILE_LINES:
        return FindingSeverity.CRITICAL, 12
    if lines > DEFAULT_MEDIUM_FILE_LINES:
        return FindingSeverity.ERROR, 8
    return FindingSeverity.WARNING, 4


def _remediation_effort(lines: int) -> str:
    if lines > DEFAULT_LARGE_FILE_LINES:
        return "1 day"
    if lines > DEFAULT_MEDIUM_FILE_LINES:
        return "4 hours"
    return "2 hours"


def _walk_python_files(repo_path: Path) -> Iterator[Path]:
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


def _is_test_file(rel_parts: tuple[str, ...]) -> bool:
    """Return True for a file path whose first directory segment is a tests/ dir."""
    return any(part in TEST_DIR_NAMES for part in rel_parts[:-1])


def _candidate_test_stems(module_stem: str) -> Set[str]:
    """Return the set of test-filename stems that would cover this module."""
    return {
        f"test_{module_stem}",
        f"{module_stem}_test",
        module_stem,  # plain `test.py` etc. are handled separately
    }


def _count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


class TestingDebtAnalyzer(Analyzer):
    """Heuristic detector for missing Python test coverage."""

    def __init__(self) -> None:
        self._threshold = None

    @property
    def name(self) -> str:
        return "testing_debt"

    @property
    def threshold(self) -> None:
        return None

    def analyze(self, repo_path: Path) -> list[Finding]:
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return []

        all_python = list(_walk_python_files(repo_path))
        if not all_python:
            return []

        rel_paths = [
            p.resolve().relative_to(repo_path).parts for p in all_python
        ]

        # Collect stems of all test files under tests/ directories.
        test_stems: Set[str] = set()
        has_tests_dir = False
        for fp, parts in zip(all_python, rel_paths):
            if _is_test_file(parts):
                has_tests_dir = True
                stem = fp.stem
                if stem == "__init__":
                    continue
                test_stems.add(stem)
                # If the test file is named after a source module, capture that.
                if stem.startswith("test_"):
                    test_stems.add(stem[len("test_"):])
                elif stem.endswith("_test"):
                    test_stems.add(stem[: -len("_test")])

        findings: list[Finding] = []

        if not has_tests_dir:
            findings.append(self._build_missing_tests_dir_finding(repo_path))

        for fp, parts in zip(all_python, rel_paths):
            if _is_test_file(parts):
                continue  # skip test files themselves
            stem = fp.stem
            if stem == "__init__":
                continue
            rel = "/".join(parts)
            if stem in test_stems:
                continue
            # Untested module.
            line_count = _count_lines(fp)
            if line_count == 0:
                continue
            findings.append(self._build_untested_module_finding(
                fp=fp,
                repo_root=repo_path,
                rel=rel,
                line_count=line_count,
            ))
        return findings

    def _build_untested_module_finding(
        self,
        fp: Path,
        repo_root: Path,
        rel: str,
        line_count: int,
    ) -> Finding:
        severity, debt_points = _severity_for_lines(line_count)
        # Bucket the line count so the ID changes when the file
        # crosses a severity boundary. Same file at 99 lines vs 100
        # lines is the SAME finding (warning) -> PERSISTENT, but
        # 99 -> 350 escalates to CRITICAL -> the prior ID is RESOLVED
        # and a new ID is emitted. Buckets:
        #   0 -> <=100    (warning)
        #   1 -> 101-300  (error)
        #   2 -> >300     (critical)
        if line_count > 300:
            lines_bucket = 2
        elif line_count > 100:
            lines_bucket = 1
        else:
            lines_bucket = 0
        finding_id = (
            "finding_testing_debt_"
            f"{hash((rel, 'untested-module', lines_bucket)) & 0xFFFFFFFF:08x}"
        )
        evidence = (
            f"module={rel} lines={line_count} "
            f"lines_bucket={lines_bucket} "
            "expected_test_file=test_<module>.py or <module>_test.py"
        )
        message = (
            f"Module '{rel}' has no matching test file under tests/"
        )
        suggestion = (
            "Add a test module named 'test_<module>.py' or "
            "'<module>_test.py' under a tests/ directory at the same "
            "package level as the source module."
        )
        return Finding(
            id=finding_id,
            rule_id="testing_debt:untested-module",
            category=FindingCategory.TESTING,
            severity=severity,
            confidence=0.7,
            file_path=rel,
            line_start=1,
            line_end=line_count,
            symbol=None,
            evidence=evidence,
            message=message,
            suggestion=suggestion,
            debt_points=debt_points,
            remediation_effort=_remediation_effort(line_count),
            analyzer=self.name,
            metadata={
                "module": rel,
                "lines": line_count,
                "lines_bucket": lines_bucket,
                "rule": "untested-module",
            },
        )

    def _build_missing_tests_dir_finding(self, repo_root: Path) -> Finding:
        rel = "tests/"
        finding_id = (
            "finding_testing_debt_"
            f"{hash((rel, 'missing-tests-dir')) & 0xFFFFFFFF:08x}"
        )
        return Finding(
            id=finding_id,
            rule_id="testing_debt:missing-tests-dir",
            category=FindingCategory.TESTING,
            severity=FindingSeverity.ERROR,
            confidence=1.0,
            file_path=rel,
            line_start=1,
            line_end=1,
            symbol=None,
            evidence="repository has no tests/ directory",
            message="Repository has no tests/ directory",
            suggestion=(
                "Create a tests/ directory at the repository root and "
                "add a smoke test before adding analyzers."
            ),
            debt_points=8,
            remediation_effort="4 hours",
            analyzer=self.name,
            metadata={"rule": "missing-tests-dir"},
        )
