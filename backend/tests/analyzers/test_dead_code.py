"""Unit tests for ``app.analyzers.dead_code`` internals.

``tests/analyzers/test_dead_code_analyzer.py`` covers the analyzer
end-to-end: the three rule families (``unreachable``,
``unused-private``, ``stale-fixture``), finding determinism, and the
security gates (lockfiles, excluded dirs, binary content, syntax
errors). This file covers the *gaps*: the module-level helpers and
builder functions that the end-to-end tests never touch directly,
plus edge-case behaviors reached only through narrower inputs:

- ``_stable_finding_id`` — ID prefix, determinism, part sensitivity.
- ``_is_test_file_rel`` — directory names, filename patterns, and the
  empty-path edge case.
- ``_is_eligible`` — called directly for symlink / outside-root paths
  the walker-level tests do not isolate.
- ``_safe_read`` — missing files and the latin-1 fallback branch.
- ``_join`` — qualname assembly.
- ``_build_unreachable_finding`` / ``_build_unused_private_finding`` /
  ``_build_stale_fixture_finding`` — full finding-field contracts
  (severity, category, confidence, debt points, metadata keys).
- ``DeadCodeAnalyzer.name`` / ``threshold`` properties.

Companion file ``tests/analyzers/test_dead_code_edges.py`` covers
terminal varieties, private-def reference edges, stale-fixture
filename patterns, and nested-scope behavior.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.analyzers.dead_code import (
    DeadCodeAnalyzer,
    _build_stale_fixture_finding,
    _build_unreachable_finding,
    _build_unused_private_finding,
    _is_eligible,
    _is_test_file_rel,
    _join,
    _safe_read,
    _stable_finding_id,
)
from app.models.finding import FindingCategory, FindingSeverity


def _private_node():
    return ast.parse("def _unused():\n    return 1\n").body[0]


class TestStableFindingId:
    def test_prefix_and_determinism(self):
        fid = _stable_finding_id("m.py", "unreachable", "f", 3, 5)
        assert fid.startswith("finding_dead_code_")
        assert fid == _stable_finding_id("m.py", "unreachable", "f", 3, 5)
        assert len(fid) == len("finding_dead_code_") + 16

    def test_different_parts_produce_different_ids(self):
        base = _stable_finding_id("m.py", "unreachable", "f", 3, 5)
        assert base != _stable_finding_id("m.py", "unreachable", "f", 3, 6)
        assert base != _stable_finding_id("m.py", "unreachable", "g", 3, 5)
        assert base != _stable_finding_id("m.py", "unused-private", "f", 3, 5)


class TestJoin:
    def test_join_with_parent(self):
        assert _join("ClassName", "method") == "ClassName.method"

    def test_join_without_parent(self):
        assert _join(None, "func") == "func"


class TestSafeRead:
    def test_missing_file_returns_none(self, tmp_path):
        assert _safe_read(tmp_path / "does_not_exist.py") is None

    def test_latin1_fallback_decodes_non_utf8(self, tmp_path):
        path = tmp_path / "latin1.py"
        path.write_bytes(b"# \xff\xfe\nx = 1\n")
        text = _safe_read(path)
        assert text is not None
        assert isinstance(text, str)


class TestIsTestFileRel:
    def test_tests_directory_names(self):
        assert _is_test_file_rel(("tests", "helper.py")) is True
        assert _is_test_file_rel(("test", "helper.py")) is True
        assert _is_test_file_rel(("tests_", "helper.py")) is True
        assert _is_test_file_rel(("src", "tests", "helper.py")) is True

    def test_filename_patterns(self):
        assert _is_test_file_rel(("src", "test_helper.py")) is True
        assert _is_test_file_rel(("src", "helper_test.py")) is True
        assert _is_test_file_rel(("src", "conftest.py")) is True
        assert _is_test_file_rel(("src", "module.py")) is False

    def test_empty_and_non_test_paths(self):
        assert _is_test_file_rel(()) is False
        assert _is_test_file_rel(("module.py",)) is False


class TestIsEligible:
    def test_python_file_is_eligible(self, tmp_path):
        root = tmp_path.resolve()
        target = root / "m.py"
        target.write_text("x = 1\n", encoding="utf-8")
        assert _is_eligible(target, root) is True

    def test_non_python_suffix_is_not_eligible(self, tmp_path):
        root = tmp_path.resolve()
        target = root / "notes.txt"
        target.write_text("x = 1\n", encoding="utf-8")
        assert _is_eligible(target, root) is False

    def test_symlink_is_not_eligible(self, tmp_path):
        root = tmp_path.resolve()
        real = root / "real.py"
        real.write_text("def _orphan():\n    return 1\n", encoding="utf-8")
        link = root / "link.py"
        link.symlink_to(real)
        assert _is_eligible(link, root) is False

    def test_file_outside_repo_root_is_not_eligible(self, tmp_path):
        root = tmp_path.resolve()
        assert _is_eligible(root / "x.py", root / "sub") is False


class TestAnalyzerProperties:
    def test_name_and_threshold(self):
        analyzer = DeadCodeAnalyzer()
        assert analyzer.name == "dead_code"
        assert analyzer.threshold is None


class TestAnalyzeEdgeCases:
    def test_missing_directory_returns_empty(self, tmp_path):
        assert DeadCodeAnalyzer().analyze(tmp_path / "missing") == []

    def test_file_path_instead_of_directory_returns_empty(self, tmp_path):
        target = tmp_path / "m.py"
        target.write_text("def _orphan():\n    return 1\n", encoding="utf-8")
        assert DeadCodeAnalyzer().analyze(target) == []


class TestUnreachableBuilder:
    def _finding(self):
        return _build_unreachable_finding(
            rel_path="m.py",
            parent_qualname="f",
            start_line=3,
            end_line=5,
            terminal_line=2,
            terminal_kind="return",
            stmt_count=3,
        )

    def test_core_fields(self):
        finding = self._finding()
        assert finding.id.startswith("finding_dead_code_")
        assert finding.rule_id == "dead_code:unreachable"
        assert finding.category == FindingCategory.MAINTAINABILITY
        assert finding.severity == FindingSeverity.WARNING
        assert finding.confidence == 1.0
        assert finding.analyzer == "dead_code"
        assert finding.debt_points == 3
        assert finding.remediation_effort == "15 minutes"

    def test_location_fields(self):
        finding = self._finding()
        assert finding.file_path == "m.py"
        assert finding.line_start == 3
        assert finding.line_end == 5
        assert finding.symbol == "f"
        assert "unreachable_statements=3" in finding.evidence

    def test_metadata_and_message(self):
        finding = self._finding()
        assert finding.metadata["rule"] == "unreachable"
        assert finding.metadata["stmt_count"] == 3
        assert finding.metadata["terminal_kind"] == "return"
        assert finding.metadata["terminal_line"] == 2
        assert "return" in finding.message
        assert "return" in finding.suggestion

    def test_module_scope_finding(self):
        finding = _build_unreachable_finding(
            rel_path="m.py",
            parent_qualname=None,
            start_line=1,
            end_line=1,
            terminal_line=1,
            terminal_kind="raise",
            stmt_count=1,
        )
        assert finding.symbol is None
        assert "at module scope" in finding.evidence


class TestUnusedPrivateBuilder:
    def _finding(self):
        return _build_unused_private_finding(
            rel_path="m.py",
            qualname="_helper",
            node=_private_node(),
            kind="function",
            reference_count=0,
        )

    def test_core_fields(self):
        finding = self._finding()
        assert finding.id.startswith("finding_dead_code_")
        assert finding.rule_id == "dead_code:unused-private"
        assert finding.category == FindingCategory.MAINTAINABILITY
        assert finding.severity == FindingSeverity.WARNING
        assert finding.confidence == 0.95
        assert finding.analyzer == "dead_code"
        assert finding.debt_points == 4
        assert finding.remediation_effort == "30 minutes"

    def test_location_and_evidence(self):
        finding = self._finding()
        assert finding.file_path == "m.py"
        assert finding.symbol == "_helper"
        assert finding.line_start == 1
        assert finding.line_end == 2
        assert "symbol=_helper" in finding.evidence
        assert "references_in_file=0" in finding.evidence
        assert finding.metadata["kind"] == "function"
        assert finding.metadata["reference_count"] == 0


class TestStaleFixtureBuilder:
    def test_core_fields(self):
        finding = _build_stale_fixture_finding(
            rel_path="tests/test_old.py",
            qualname="old_helper",
            kind="function",
            references_in_repo=0,
            start_line=4,
        )
        assert finding.id.startswith("finding_dead_code_")
        assert finding.rule_id == "dead_code:stale-fixture"
        assert finding.category == FindingCategory.TESTING
        assert finding.severity == FindingSeverity.INFO
        assert finding.confidence == 0.85
        assert finding.analyzer == "dead_code"
        assert finding.debt_points == 2
        assert finding.remediation_effort == "15 minutes"

    def test_location_and_metadata(self):
        finding = _build_stale_fixture_finding(
            rel_path="tests/test_old.py",
            qualname="old_helper",
            kind="function",
            references_in_repo=0,
            start_line=4,
        )
        assert finding.file_path == "tests/test_old.py"
        assert finding.symbol == "old_helper"
        assert finding.line_start == 4
        assert finding.line_end == 4
        assert "test_symbol=old_helper" in finding.evidence
        assert finding.metadata["rule"] == "stale-fixture"
        assert finding.metadata["references_in_repo"] == 0

