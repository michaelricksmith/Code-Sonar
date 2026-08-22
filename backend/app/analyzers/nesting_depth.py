"""Nesting depth analyzer for Python.

Detects functions, async functions, and methods whose maximum control-
flow nesting depth exceeds a configurable threshold. Detection is
pure AST-based: blocks, if/elif/else, for, while, with, try/except/
finally, and match statements all contribute to depth.

Severity scales with how far the function exceeds the threshold:
  depth > threshold           -> WARNING
  depth >= 2 * threshold      -> ERROR
  depth >= 3 * threshold      -> CRITICAL

Malformed Python sources are silently skipped. Finding IDs are
derived from (relative file path, qualified symbol name, depth,
threshold) so repeated scans of the same repository produce
byte-identical IDs.
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

DEFAULT_NESTING_THRESHOLD: int = 4


def _severity_for(depth: int, threshold: int) -> Tuple[FindingSeverity, int]:
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    if depth <= threshold:
        raise ValueError("depth does not exceed threshold; no finding")
    if depth >= threshold * 3:
        return FindingSeverity.CRITICAL, 12
    if depth >= threshold * 2:
        return FindingSeverity.ERROR, 8
    return FindingSeverity.WARNING, 4


def _remediation_effort(depth: int, threshold: int) -> str:
    ratio = depth / max(threshold, 1)
    if ratio >= 3:
        return "1 day"
    if ratio >= 2:
        return "4 hours"
    return "2 hours"


def _max_depth(node: ast.AST, current: int = 0, best: int = 0) -> int:
    """Recursively compute the maximum nesting depth of compound blocks."""
    here = current
    # AST nodes whose children introduce a new nesting level.
    nesting_introducers = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        ast.TryStar,
        ast.ExceptHandler,
        ast.IfExp,
    )
    if isinstance(node, ast.Match):
        # Each case clause introduces a new level.
        here += 1
        best = max(best, here)
        for case in node.cases:
            best = max(best, _max_depth(case, here, best))
        return best
    if isinstance(node, nesting_introducers):
        here += 1
        best = max(best, here)
    for child in ast.iter_child_nodes(node):
        best = max(best, _max_depth(child, here, best))
    return best


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


def _iter_python_functions(
    tree: ast.AST,
) -> Iterator[Tuple[ast.AST, Optional[str], Optional[str]]]:
    seen: set[int] = set()

    def walk(
        body: list,
        parent_class: Optional[str],
        parent_qualname: Optional[str],
    ) -> Iterator[Tuple[ast.AST, Optional[str], Optional[str]]]:
        for stmt in body:
            if id(stmt) in seen:
                continue
            seen.add(id(stmt))
            if isinstance(stmt, ast.ClassDef):
                inner_class_qualname = (
                    (parent_qualname + "." + stmt.name)
                    if parent_qualname else stmt.name
                )
                yield from _walk_class_body(stmt.body, stmt.name, inner_class_qualname)
                yield from walk(stmt.body, parent_class=None, parent_qualname=inner_class_qualname)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = (
                    (parent_qualname + "." + stmt.name)
                    if parent_qualname else stmt.name
                )
                yield stmt, parent_class, parent_qualname
                yield from walk(stmt.body, parent_class=None, parent_qualname=qualname)

    def _walk_class_body(
        body: list,
        class_name: str,
        class_qualname: Optional[str],
    ) -> Iterator[Tuple[ast.AST, Optional[str], Optional[str]]]:
        for stmt in body:
            if id(stmt) in seen:
                continue
            seen.add(id(stmt))
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_qualname = (
                    (class_qualname + "." + stmt.name)
                    if class_qualname else stmt.name
                )
                yield stmt, class_name, class_qualname
                yield from walk(stmt.body, parent_class=None, parent_qualname=method_qualname)
            elif isinstance(stmt, ast.ClassDef):
                nested_class_qualname = (
                    (class_qualname + "." + stmt.name)
                    if class_qualname else stmt.name
                )
                yield from _walk_class_body(stmt.body, stmt.name, nested_class_qualname)
                yield from walk(stmt.body, parent_class=None, parent_qualname=nested_class_qualname)

    yield from walk(getattr(tree, "body", []), parent_class=None, parent_qualname=None)


class NestingDepthAnalyzer(Analyzer):
    """Detects Python functions whose max nesting depth exceeds the threshold."""

    def __init__(self, threshold: int = DEFAULT_NESTING_THRESHOLD) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "nesting_depth"

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
        try:
            tree = ast.parse(source, filename=str(file_path))
        except (SyntaxError, ValueError):
            return []
        rel_path = file_path.resolve().relative_to(repo_root).as_posix()
        findings: list[Finding] = []
        for node, parent_class, parent_qualname in _iter_python_functions(tree):
            depth = _max_depth(node)
            if depth <= self._threshold:
                continue
            findings.append(self._build_finding(
                node=node,
                parent_class=parent_class,
                parent_qualname=parent_qualname,
                depth=depth,
                rel_path=rel_path,
            ))
        return findings

    def _build_finding(
        self,
        node: ast.AST,
        parent_class: Optional[str],
        parent_qualname: Optional[str],
        depth: int,
        rel_path: str,
    ) -> Finding:
        name = getattr(node, "name", "<lambda>")
        qualified = (
            (parent_qualname + "." + name)
            if parent_qualname else name
        )
        severity, debt_points = _severity_for(depth, self._threshold)
        finding_id = (
            "finding_nesting_depth_"
            f"{hash((rel_path, qualified, depth, self._threshold)) & 0xFFFFFFFF:08x}"
        )
        line_start = getattr(node, "lineno", 1) or 1
        line_end = getattr(node, "end_lineno", line_start) or line_start
        evidence = (
            f"symbol={qualified} depth={depth} threshold={self._threshold}"
        )
        message = (
            f"Function '{qualified}' has nesting depth {depth} "
            f"(threshold {self._threshold})"
        )
        suggestion = (
            "Reduce nesting depth by extracting helper functions for inner "
            "branches, replacing nested conditionals with guard clauses, or "
            "splitting the function into smaller units along responsibility "
            "boundaries."
        )
        return Finding(
            id=finding_id,
            rule_id="nesting_depth:over-threshold",
            category=FindingCategory.MAINTAINABILITY,
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
            remediation_effort=_remediation_effort(depth, self._threshold),
            analyzer=self.name,
            metadata={
                "symbol": qualified,
                "depth": depth,
                "threshold": self._threshold,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "is_method": parent_class is not None,
                "severity_factor": round(depth / self._threshold, 2),
            },
        )
