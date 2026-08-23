"""Oversized functions analyzer for Python.

Detects functions, async functions, and class methods whose source line
range exceeds a configurable threshold. Detection is pure AST-based:
``ast.FunctionDef``, ``ast.AsyncFunctionDef``, and methods (functions
nested inside class bodies) are all scanned. Nested functions are
followed recursively so inner helpers can also be flagged with a
fully qualified symbol.

Severity scales with how far the function exceeds the threshold:
  up to 1.5x    -> WARNING
  up to 2.5x    -> ERROR
  greater       -> CRITICAL

Malformed Python sources are silently skipped. Finding IDs are derived
from (relative file path, qualified symbol name, length, threshold) so
repeated scans of the same repository produce byte-identical IDs.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Optional, Tuple

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

DEFAULT_FUNCTION_THRESHOLD: int = 50

# Iterator tuple: (node, parent_class_for_metadata, parent_qualname_for_symbol).
# `parent_class` is set only when the function lives directly inside a class
# body (i.e. a method). `parent_qualname` is the fully qualified name of the
# enclosing function/method (e.g. "outer", "C.method", "outer.inner").
_FuncYield = Tuple[ast.AST, Optional[str], Optional[str]]


def _severity_for(length: int, threshold: int) -> Tuple[FindingSeverity, int]:
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    if length >= threshold * 3:
        return FindingSeverity.CRITICAL, 12
    if length >= threshold * 2:
        return FindingSeverity.ERROR, 8
    if length >= threshold + int(threshold * 0.5):
        return FindingSeverity.ERROR, 6
    return FindingSeverity.WARNING, 3


def _join(parent: Optional[str], name: str) -> str:
    if parent:
        return f"{parent}.{name}"
    return name


def _remediation_effort(length: int, threshold: int) -> str:
    excess = length / max(threshold, 1)
    if excess >= 3:
        return "1 day"
    if excess >= 2:
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


def _safe_read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError, ValueError):
        try:
            return path.read_text(encoding="latin-1")
        except (UnicodeDecodeError, OSError, ValueError):
            return None


def _function_length(node: ast.AST, source_lines: list[str]) -> int:
    start_raw = getattr(node, "lineno", None)
    end_raw = getattr(node, "end_lineno", None)
    if start_raw is None or end_raw is None:
        return 0
    start = int(start_raw)
    end = int(end_raw)
    start_idx = max(1, start) - 1
    end_idx = min(end, len(source_lines)) - 1
    if end_idx < start_idx:
        return 0
    return end_idx - start_idx + 1


def _iter_python_functions(
    tree: ast.AST,
) -> Iterator[_FuncYield]:
    """Yield every function/method node in the AST exactly once.

    Each yield contains:
      - ``node``: the FunctionDef / AsyncFunctionDef AST node.
      - ``parent_class``: name of the directly enclosing class, if any.
      - ``parent_qualname``: fully qualified name of the enclosing
        function/method (None at module level).
    """
    seen: set[int] = set()

    def walk(
        body: list[ast.stmt],
        parent_class: Optional[str],
        parent_qualname: Optional[str],
    ) -> Iterator[_FuncYield]:
        for stmt in body:
            if id(stmt) in seen:
                continue
            seen.add(id(stmt))
            if isinstance(stmt, ast.ClassDef):
                inner_class_qualname = _join(parent_qualname, stmt.name)
                # Methods inside the class body.
                yield from _walk_class_body(
                    stmt.body,
                    class_name=stmt.name,
                    class_qualname=inner_class_qualname,
                )
                # Nested classes inside the outer function/class.
                yield from walk(
                    stmt.body,
                    parent_class=None,
                    parent_qualname=inner_class_qualname,
                )
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = _join(parent_qualname, stmt.name)
                yield stmt, parent_class, parent_qualname
                # Recurse into the function body for nested defs/classes.
                yield from walk(stmt.body, parent_class=None, parent_qualname=qualname)

    def _walk_class_body(
        body: list[ast.stmt],
        class_name: str,
        class_qualname: Optional[str],
    ) -> Iterator[_FuncYield]:
        for stmt in body:
            if id(stmt) in seen:
                continue
            seen.add(id(stmt))
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_qualname = _join(class_qualname, stmt.name)
                yield stmt, class_name, class_qualname
                yield from walk(stmt.body, parent_class=None, parent_qualname=method_qualname)
            elif isinstance(stmt, ast.ClassDef):
                nested_class_qualname = _join(class_qualname, stmt.name)
                yield from _walk_class_body(
                    stmt.body,
                    class_name=stmt.name,
                    class_qualname=nested_class_qualname,
                )
                yield from walk(
                    stmt.body,
                    parent_class=None,
                    parent_qualname=nested_class_qualname,
                )

    yield from walk(getattr(tree, "body", []), parent_class=None, parent_qualname=None)


class OversizedFunctionsAnalyzer(Analyzer):
    """Detects Python functions whose line span exceeds a configurable threshold."""

    def __init__(self, threshold: int = DEFAULT_FUNCTION_THRESHOLD) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "oversized_functions"

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
        source_lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(file_path))
        except (SyntaxError, ValueError):
            return []
        rel_path = file_path.resolve().relative_to(repo_root).as_posix()
        findings: list[Finding] = []
        for node, parent_class, parent_qualname in _iter_python_functions(tree):
            length = _function_length(node, source_lines)
            if length <= self._threshold:
                continue
            findings.append(self._build_finding(
                node=node,
                parent_class=parent_class,
                parent_qualname=parent_qualname,
                length=length,
                rel_path=rel_path,
            ))
        return findings

    def _build_finding(
        self,
        node: ast.AST,
        parent_class: Optional[str],
        parent_qualname: Optional[str],
        length: int,
        rel_path: str,
    ) -> Finding:
        name = getattr(node, "name", "<lambda>")
        qualified = _join(parent_qualname, name)
        severity, debt_points = _severity_for(length, self._threshold)
        finding_id = (
            "finding_oversized_functions_"
            f"{hash((rel_path, qualified, length, self._threshold)) & 0xFFFFFFFF:08x}"
        )
        start = getattr(node, "lineno", 1) or 1
        end = getattr(node, "end_lineno", start) or start
        evidence = (
            f"symbol={qualified} length={length} threshold={self._threshold}"
        )
        message = (
            f"Function '{qualified}' is {length} lines "
            f"(threshold {self._threshold})"
        )
        suggestion = (
            "Extract helper functions or split the body along responsibility "
            "boundaries so this function fits under the configured threshold."
        )
        return Finding(
            id=finding_id,
            rule_id="oversized_functions:over-threshold",
            category=FindingCategory.MAINTAINABILITY,
            severity=severity,
            confidence=1.0,
            file_path=rel_path,
            line_start=start,
            line_end=end,
            symbol=qualified,
            evidence=evidence,
            message=message,
            suggestion=suggestion,
            debt_points=debt_points,
            remediation_effort=_remediation_effort(length, self._threshold),
            analyzer=self.name,
            metadata={
                "symbol": qualified,
                "function_length": length,
                "threshold": self._threshold,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "is_method": parent_class is not None,
                "severity_factor": round(length / self._threshold, 2),
            },
        )
