"""Unit tests for ``app.analyzers.dead_code`` — terminal and reference edges.

Companion to ``tests/analyzers/test_dead_code.py`` (which covers the
module-level helpers and finding builders); this file covers the
behaviors reached only through narrower analyzer inputs:

- Terminal varieties the family tests skip: ``continue``, and
  terminals inside ``try`` / ``except`` / ``finally`` blocks.
- Reference edges for private defs: module-level ``Name`` refs,
  attribute refs, and ``from ... import`` refs.
- Stale-fixture filename patterns (``test_*.py``, ``*_test.py`` at the
  repo root), cross-test-file imports, source imports, and the
  ``pytestmark`` / ``conftest`` skips.
- Nested-scope behavior: nested defs are not collected as private
  defs (documenting the analyzer's conservative local-scope rule),
  while unreachable code inside a nested def is still found.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.analyzers.dead_code import DeadCodeAnalyzer


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _rules(findings):
    return [f.rule_id for f in findings]


def _of_rule(findings, rule_id):
    return [f for f in findings if f.rule_id == rule_id]


class TestTerminalVarieties:
    def test_continue_in_while_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n" "    while True:\n" "        continue\n" "        tick()\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:unreachable")
        assert len(findings) == 1
        assert findings[0].metadata["terminal_kind"] == "continue"

    def test_return_inside_try_body_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n"
            "    try:\n"
            "        return 1\n"
            "        cleanup()\n"
            "    except ValueError:\n"
            "        pass\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:unreachable")
        assert len(findings) == 1
        assert findings[0].metadata["stmt_count"] == 1

    def test_terminal_inside_except_handler_not_detected(self, tmp_path):
        # Documents a conservative boundary: ``_find_unreachable``
        # recurses into ``handlers`` as ``ExceptHandler`` nodes, so a
        # terminal inside an ``except`` body never yields a finding.
        _write(
            tmp_path / "m.py",
            "def f():\n"
            "    try:\n"
            "        work()\n"
            "    except ValueError:\n"
            "        raise\n"
            "        log()\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:unreachable")
        assert findings == []

    def test_return_inside_finally_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n"
            "    try:\n"
            "        work()\n"
            "    finally:\n"
            "        return\n"
            "        after()\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:unreachable")
        assert len(findings) == 1
        assert findings[0].metadata["terminal_kind"] == "return"

    def test_separate_runs_in_branches_are_separate_findings(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f(x):\n"
            "    if x:\n"
            "        return 1\n"
            "        a = 1\n"
            "    else:\n"
            "        return 2\n"
            "        b = 2\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:unreachable")
        assert len(findings) == 2
        assert findings[0].id != findings[1].id

    def test_unreachable_inside_nested_function_found(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def outer():\n"
            "    def inner():\n"
            "        return 1\n"
            "        x = 2\n"
            "    return inner\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:unreachable")
        assert len(findings) == 1
        assert findings[0].symbol == "inner"


class TestPrivateReferenceEdges:
    def test_module_level_name_reference_counts(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def _helper():\n" "    return 1\n" "\n" "handle = _helper\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:unused-private" not in _rules(findings)

    def test_attribute_reference_counts(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def _helper():\n" "    return 1\n" "\n" "value = obj._helper()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:unused-private" not in _rules(findings)

    def test_from_import_reference_counts(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "from elsewhere import _helper\n" "\n" "def _helper():\n" "    return 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:unused-private" not in _rules(findings)

    def test_plain_import_adds_top_level_name(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "import elsewhere\n" "\n" "def _helper():\n" "    return elsewhere.run()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert ("dead_code:unused-private", "_helper") in [
            (f.rule_id, f.symbol) for f in findings
        ]


class TestStaleFixtureEdges:
    def test_test_prefix_file_at_root_flagged(self, tmp_path):
        _write(
            tmp_path / "test_root.py",
            "def stale_root_helper():\n" "    return 1\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:stale-fixture")
        assert len(findings) == 1
        assert findings[0].symbol == "stale_root_helper"

    def test_test_suffix_file_at_root_flagged(self, tmp_path):
        _write(
            tmp_path / "helpers_test.py",
            "def stale_suffix_helper():\n" "    return 1\n",
        )
        findings = _of_rule(DeadCodeAnalyzer().analyze(tmp_path), "dead_code:stale-fixture")
        assert len(findings) == 1
        assert findings[0].symbol == "stale_suffix_helper"

    def test_helper_referenced_internally_not_stale(self, tmp_path):
        test_dir = tmp_path / "tests"
        _write(
            test_dir / "test_inner.py",
            "def build_thing():\n"
            "    return 1\n"
            "\n"
            "def test_thing():\n"
            "    assert build_thing() == 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:stale-fixture" not in _rules(findings)

    def test_helper_imported_by_another_test_file_not_stale(self, tmp_path):
        test_dir = tmp_path / "tests"
        _write(
            test_dir / "test_a.py",
            "def shared_helper():\n" "    return 1\n",
        )
        _write(
            test_dir / "test_b.py",
            "from test_a import shared_helper\n"
            "\n"
            "def test_shared():\n"
            "    assert shared_helper() == 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:stale-fixture" not in _rules(findings)

    def test_helper_imported_by_source_not_stale(self, tmp_path):
        test_dir = tmp_path / "tests"
        _write(
            test_dir / "test_x.py",
            "def sourced_helper():\n" "    return 1\n",
        )
        _write(
            tmp_path / "src" / "mod.py",
            "from test_x import sourced_helper\n" "\n" "VALUE = sourced_helper()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:stale-fixture" not in _rules(findings)

    def test_pytestmark_definition_skipped(self, tmp_path):
        test_dir = tmp_path / "tests"
        _write(
            test_dir / "test_marked.py",
            "def pytestmark():\n" "    return []\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:stale-fixture" not in _rules(findings)

    def test_conftest_definition_skipped(self, tmp_path):
        test_dir = tmp_path / "tests"
        _write(
            test_dir / "conftest.py",
            "def conftest():\n" "    return 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:stale-fixture" not in _rules(findings)


class TestNestedScopeBehavior:
    def test_nested_private_def_not_collected(self, tmp_path):
        # Nested defs live in local scope, so the analyzer does not
        # track them as file-level private definitions at all.
        _write(
            tmp_path / "m.py",
            "def outer():\n"
            "    def _inner():\n"
            "        return 1\n"
            "    return _inner()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:unused-private" not in _rules(findings)

    def test_private_def_referenced_only_by_nested_def_counts(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def _helper():\n"
            "    return 1\n"
            "\n"
            "def outer():\n"
            "    def inner():\n"
            "        return _helper()\n"
            "    return inner\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert "dead_code:unused-private" not in _rules(findings)
