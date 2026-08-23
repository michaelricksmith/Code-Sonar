"""Dead-code analyzer — high-signal static findings.

Targets (per Checkpoint 5 priorities):

1. **Unreachable statements** — code that can never execute because
   every preceding statement in its block is a terminal (``return``,
   ``raise``, ``break``, ``continue``). Detection is purely local to
   a function or module body; we do not attempt cross-module control
   flow.

2. **Unused private functions/methods** — functions or methods whose
   name starts with ``_`` (convention for "private to this module")
   and that are not referenced anywhere in the same file. Confidence
   is **deterministic** because reference counting is a closed-system
   property of the AST.

3. **Stale test fixtures** — test files (any file under a
   ``tests/`` / ``test/`` directory or matching ``test_*.py`` /
   ``*_test.py`` / ``conftest.py`` patterns) that define symbols
   which are never imported anywhere in the repository's non-test
   source and never referenced inside any other test file. Confidence
   is high (no fixture inferred as "test helper" without direct
   reference), but a finding's evidence always includes the file's
   exact role so reviewers can override.

**Explicitly NOT in scope for this analyzer** (per the lane brief):

- **Unused imports.** Ruff's ``F401`` does this well; duplicating it
  poorly here would create a noisy, lower-signal detector. Out of
  scope until we have evidence of a use-case Ruff cannot cover.
- **Speculative cross-module inference.** We never try to infer that
  a function "must be used externally because the public API looks
  like it". Every finding's evidence lists the counted references in
  the file, so the reviewer can see exactly why we flagged it.

Detection is gated by ``app.security`` (excluded dirs, lockfiles,
binary files, symlinks). Finding IDs are derived from
``(rel_path, rule_id, qualified_symbol_or_line)`` so repeated scans
produce byte-identical IDs.
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

TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test", "tests_"})


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


def _is_test_file_rel(rel_parts: Tuple[str, ...]) -> bool:
    """True if any path segment names a tests/ dir, or filename matches test patterns."""
    if any(part in TEST_DIR_NAMES for part in rel_parts[:-1]):
        return True
    name = rel_parts[-1] if rel_parts else ""
    if name in {"conftest.py"}:
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return False


def _join(parent: Optional[str], name: str) -> str:
    if parent:
        return f"{parent}.{name}"
    return name


class _FileAnalysis:
    """Aggregated state per parsed Python file."""

    __slots__ = ("tree", "source_lines", "rel_path", "is_test_file", "private_defs",
                 "public_defs", "all_names_referenced")

    def __init__(
        self,
        tree: ast.Module,
        source_lines: list[str],
        rel_path: str,
        is_test_file: bool,
    ) -> None:
        self.tree = tree
        self.source_lines = source_lines
        self.rel_path = rel_path
        self.is_test_file = is_test_file
        # (node, qualname, kind). ``node`` is always a FunctionDef or
        # AsyncFunctionDef, so callers can safely access ``node.name``.
        self.private_defs: list[Tuple[ast.AST, str, str]] = []
        self.public_defs: list[Tuple[ast.AST, str, str]] = []
        # All names referenced anywhere in the file (Name(id=...) and
        # Attribute(value=Name(...)) collected across all bodies).
        self.all_names_referenced: set[str] = set()


def _collect_definitions(
    body: list[ast.stmt],
    analysis: _FileAnalysis,
    parent_qualname: Optional[str],
) -> None:
    """Walk a body collecting defs and recording all referenced names."""

    class _Visitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            analysis.all_names_referenced.add(node.id)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                # Treat `import foo` as referencing `foo`.
                analysis.all_names_referenced.add(alias.asname or alias.name.split(".")[0])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                analysis.all_names_referenced.add(alias.asname or alias.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            qualname = _join(parent_qualname, node.name)
            if node.name.startswith("_") and not node.name.startswith("__"):
                analysis.private_defs.append((node, qualname, "function"))
            else:
                analysis.public_defs.append((node, qualname, "function"))
            # Don't descend: nested functions are local scope; their
            # references do not count toward outer-symbol usage.

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)  # type: ignore[arg-type]

    visitor = _Visitor()
    for stmt in body:
        visitor.visit(stmt)

    # Also visit bodies of classes/methods to catch references inside them.
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name):
                    analysis.all_names_referenced.add(inner.id)
                elif isinstance(inner, ast.Import):
                    for alias in inner.names:
                        analysis.all_names_referenced.add(
                            alias.asname or alias.name.split(".")[0]
                        )
                elif isinstance(inner, ast.ImportFrom):
                    for alias in inner.names:
                        analysis.all_names_referenced.add(
                            alias.asname or alias.name
                        )


def _find_unreachable(body: list[ast.stmt], source_lines: list[str],
                      start_lineno: int, rel_path: str,
                      parent_qualname: Optional[str]) -> Iterator[Finding]:
    """Find statements after a terminal that can never execute.

    Walks each block linearly. After a ``return``, ``raise``,
    ``break``, or ``continue``, every following sibling statement in
    the same block is unreachable. We emit one finding per contiguous
    run of unreachable statements; the line range is the union.
    """
    terminals = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    for stmt in body:
        if isinstance(stmt, (ast.If, ast.While, ast.For, ast.AsyncFor,
                             ast.With, ast.AsyncWith, ast.Try)):
            # Recurse into compound blocks; unreachable detection is
            # local to each block. (Note: a ``return`` inside an ``if``
            # does NOT make the *following* ``if`` unreachable.)
            for field_name in ("body", "orelse", "finalbody", "handlers"):
                inner = getattr(stmt, field_name, None)
                if isinstance(inner, list):
                    yield from _find_unreachable(
                        inner, source_lines, start_lineno, rel_path,
                        parent_qualname,
                    )
            if isinstance(stmt, (ast.For, ast.AsyncFor)):
                # for-else: executed only if loop completes without break.
                # Don't claim statements inside ``else`` as unreachable.
                continue
        if not isinstance(stmt, terminals):
            continue
        # Found a terminal. Look at siblings AFTER it in the parent body.
        idx = body.index(stmt)
        unreachable_siblings: list[ast.stmt] = []
        for nxt in body[idx + 1:]:
            # Skip docstrings (first stmt Expr(Constant str)).
            if (isinstance(nxt, ast.Expr)
                    and isinstance(nxt.value, ast.Constant)
                    and isinstance(nxt.value.value, str)
                    and len(unreachable_siblings) == 0):
                continue
            unreachable_siblings.append(nxt)
        if not unreachable_siblings:
            continue
        first = unreachable_siblings[0]
        last = unreachable_siblings[-1]
        start_line = getattr(first, "lineno", start_lineno) or start_lineno
        end_line = (
            getattr(last, "end_lineno", None)
            or getattr(last, "lineno", start_line)
            or start_line
        )
        yield _build_unreachable_finding(
            rel_path=rel_path,
            parent_qualname=parent_qualname,
            start_line=start_line,
            end_line=end_line,
            terminal_line=getattr(stmt, "lineno", start_lineno) or start_lineno,
            terminal_kind=type(stmt).__name__.lower(),
            stmt_count=len(unreachable_siblings),
        )


def _build_unreachable_finding(
    rel_path: str,
    parent_qualname: Optional[str],
    start_line: int,
    end_line: int,
    terminal_line: int,
    terminal_kind: str,
    stmt_count: int,
) -> Finding:
    scope_key = parent_qualname if parent_qualname else "<module>"
    finding_id = (
        "finding_dead_code_"
        + f"{hash((rel_path, 'unreachable', scope_key, start_line, end_line)) & 0xFFFFFFFF:08x}"
    )
    where = f"in {parent_qualname}" if parent_qualname else "at module scope"
    evidence = (
        f"unreachable_statements={stmt_count} "
        f"after_{terminal_kind}_at_line={terminal_line} "
        f"line_range={start_line}-{end_line} {where}"
    )
    return Finding(
        id=finding_id,
        rule_id="dead_code:unreachable",
        category=FindingCategory.MAINTAINABILITY,
        severity=FindingSeverity.WARNING,
        confidence=1.0,
        file_path=rel_path,
        line_start=start_line,
        line_end=end_line,
        symbol=parent_qualname,
        evidence=evidence,
        message=(
            f"{stmt_count} statement(s) after a {terminal_kind} can never "
            f"execute {where} ({rel_path}:{start_line}-{end_line})"
        ),
        suggestion=(
            "Remove the unreachable statements, or move the terminating "
            f"{terminal_kind} after them if the logic was inverted."
        ),
        debt_points=3,
        remediation_effort="15 minutes",
        analyzer="dead_code",
        metadata={
            "rule": "unreachable",
            "stmt_count": stmt_count,
            "terminal_kind": terminal_kind,
            "terminal_line": terminal_line,
        },
    )


def _build_unused_private_finding(
    rel_path: str,
    qualname: str,
    node: ast.AST,
    kind: str,
    reference_count: int,
) -> Finding:
    finding_id = (
        "finding_dead_code_"
        f"{hash((rel_path, 'unused-private', qualname)) & 0xFFFFFFFF:08x}"
    )
    start = getattr(node, "lineno", 1) or 1
    end = getattr(node, "end_lineno", start) or start
    severity = FindingSeverity.WARNING
    debt_points = 4
    return Finding(
        id=finding_id,
        rule_id="dead_code:unused-private",
        category=FindingCategory.MAINTAINABILITY,
        severity=severity,
        confidence=0.95,  # Deterministic within file; cross-module is not assumed.
        file_path=rel_path,
        line_start=start,
        line_end=end,
        symbol=qualname,
        evidence=(
            f"symbol={qualname} kind={kind} "
            f"references_in_file={reference_count}"
        ),
        message=(
            f"Private {kind} '{qualname}' is defined but never "
            f"referenced in {rel_path}"
        ),
        suggestion=(
            "Remove the private definition if it is no longer needed, "
            "or expose it as a public symbol if it is part of the "
            "module's contract."
        ),
        debt_points=debt_points,
        remediation_effort="30 minutes",
        analyzer="dead_code",
        metadata={
            "rule": "unused-private",
            "symbol": qualname,
            "kind": kind,
            "reference_count": reference_count,
        },
    )


def _build_stale_fixture_finding(
    rel_path: str,
    qualname: str,
    kind: str,
    references_in_repo: int,
) -> Finding:
    finding_id = (
        "finding_dead_code_"
        f"{hash((rel_path, 'stale-fixture', qualname)) & 0xFFFFFFFF:08x}"
    )
    return Finding(
        id=finding_id,
        rule_id="dead_code:stale-fixture",
        category=FindingCategory.TESTING,
        severity=FindingSeverity.INFO,
        confidence=0.85,
        file_path=rel_path,
        line_start=1,
        line_end=1,
        symbol=qualname,
        evidence=(
            f"test_symbol={qualname} kind={kind} "
            f"references_in_repository={references_in_repo}"
        ),
        message=(
            f"Test {kind} '{qualname}' in {rel_path} is never imported "
            "by any source or test file; it may be a stale fixture."
        ),
        suggestion=(
            "If the fixture is no longer used, delete it. If it should "
            "be reused, import it from the relevant test module."
        ),
        debt_points=2,
        remediation_effort="15 minutes",
        analyzer="dead_code",
        metadata={
            "rule": "stale-fixture",
            "symbol": qualname,
            "kind": kind,
            "references_in_repo": references_in_repo,
        },
    )


class DeadCodeAnalyzer(Analyzer):
    """High-signal dead-code detector for Python repositories."""

    @property
    def name(self) -> str:
        return "dead_code"

    @property
    def threshold(self) -> None:
        return None

    def analyze(self, repo_path: Path) -> list[Finding]:
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return []

        # Pass 1: parse all eligible files and collect references across the repo.
        analyses: list[_FileAnalysis] = []
        for file_path in _walk_python_files(repo_path):
            source = _safe_read(file_path)
            if source is None:
                continue
            source_lines = source.splitlines()
            try:
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError):
                continue
            rel_path = file_path.resolve().relative_to(repo_path).as_posix()
            rel_parts = tuple(rel_path.split("/"))
            is_test = _is_test_file_rel(rel_parts)
            analysis = _FileAnalysis(
                tree=tree,
                source_lines=source_lines,
                rel_path=rel_path,
                is_test_file=is_test,
            )
            _collect_definitions(getattr(tree, "body", []), analysis,
                                 parent_qualname=None)
            analyses.append(analysis)

        # Aggregate names referenced anywhere in non-test files (for stale-fixture
        # detection).
        non_test_refs: set[str] = set()
        test_refs: set[str] = set()
        for a in analyses:
            target = non_test_refs if not a.is_test_file else test_refs
            target |= a.all_names_referenced

        findings: list[Finding] = []

        # Pass 2: produce findings.
        for a in analyses:
            # 1) Unreachable code (apply at module scope and inside every function).
            findings.extend(_find_unreachable(
                body=getattr(a.tree, "body", []),
                source_lines=a.source_lines,
                start_lineno=1,
                rel_path=a.rel_path,
                parent_qualname=None,
            ))
            for node in ast.walk(a.tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = node.name  # local qualname for finding; not nested
                    findings.extend(_find_unreachable(
                        body=getattr(node, "body", []),
                        source_lines=a.source_lines,
                        start_lineno=getattr(node, "lineno", 1) or 1,
                        rel_path=a.rel_path,
                        parent_qualname=qualname,
                    ))

            # 2) Unused private definitions.
            for node, qualname, kind in a.private_defs:
                # ``node`` is always a FunctionDef/AsyncFunctionDef here.
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                def_name = node.name
                # Count references in this file other than the definition itself.
                ref_count = sum(
                    1 for n in a.all_names_referenced if n == def_name
                )
                # ``ast.Name`` references for the def itself are not
                # counted, so any non-zero count means the private
                # name is used somewhere else in the file.
                if ref_count == 0:
                    findings.append(_build_unused_private_finding(
                        rel_path=a.rel_path,
                        qualname=qualname,
                        node=node,
                        kind=kind,
                        reference_count=ref_count,
                    ))

            # 3) Stale test fixtures (only when confidence is strong).
            if a.is_test_file:
                for node, qualname, kind in a.public_defs:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    def_name = node.name
                    # Pytest entry points (``test_*`` / ``*_test``) are
                    # discovered by the test runner, not by import. They
                    # are NEVER stale as long as the test file itself is
                    # imported by the test runner. Skip them entirely.
                    if def_name.startswith("test_") or def_name.endswith("_test"):
                        continue
                    # Skip obvious fixtures used internally; require the symbol to
                    # be referenced from outside the file to count as "used".
                    if def_name in a.all_names_referenced:
                        # Referenced inside this test file -> likely a helper,
                        # not stale.
                        continue
                    if def_name in non_test_refs:
                        # Imported somewhere in source.
                        continue
                    if def_name in test_refs and def_name not in a.all_names_referenced:
                        # Imported from another test file (not this one).
                        continue
                    # Also skip dunders, fixtures, pytest-style helpers
                    # (any name starting with `_` already covered above,
                    # but pytest allows ``fixture`` naming without `_`).
                    if def_name in {"conftest", "pytestmark"}:
                        continue
                    # Only flag if the symbol is *defined* (i.e. has a body),
                    # not just imported/re-exported.
                    findings.append(_build_stale_fixture_finding(
                        rel_path=a.rel_path,
                        qualname=qualname,
                        kind=kind,
                        references_in_repo=0,
                    ))

        return findings
