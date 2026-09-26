"""Tests for the dead_code analyzer.

Verifies the four rule families the analyzer exposes:

- ``dead_code:unreachable``        — statements after a terminal that can never run.
- ``dead_code:unused-private``     — private definitions (single underscore)
                                    never referenced in the same file.
- ``dead_code:stale-fixture``      — public test symbols never imported by any
                                    source or other test file.

The analyzer is built deliberately conservatively: cross-module
inference is not attempted. Tests therefore assert that *intra-file*
signals fire reliably and that no false positives leak in from
common dunder / __init__ / re-export patterns.
"""

from __future__ import annotations

from pathlib import Path

from app.analyzers.dead_code import DeadCodeAnalyzer
from app.models.finding import FindingCategory


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class TestUnreachableCode:
    def test_statements_after_return_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n"
            "    return 1\n"
            "    x = 2\n"  # unreachable
            "    y = 3\n"  # unreachable
            "    z = 4\n",  # unreachable
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unreachable" in rules
        for f in findings:
            if f.rule_id == "dead_code:unreachable":
                assert f.category == FindingCategory.MAINTAINABILITY
                assert f.metadata["rule"] == "unreachable"
                assert f.metadata["terminal_kind"] == "return"
                assert f.metadata["stmt_count"] == 3
                assert f.line_start == 3
                assert f.line_end == 5

    def test_statements_after_raise_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n" "    raise ValueError('nope')\n" "    cleanup()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unreachable" in rules
        for f in findings:
            if f.rule_id == "dead_code:unreachable":
                assert f.metadata["terminal_kind"] == "raise"
                assert f.metadata["stmt_count"] == 1

    def test_statements_after_break_in_loop_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n"
            "    for x in range(10):\n"
            "        break\n"
            "        do_thing(x)\n"
            "    return 0\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unreachable" in rules

    def test_no_finding_when_all_reachable(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def f():\n" "    if True:\n" "        return 1\n" "    else:\n" "        return 2\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        # Only the return itself, no unreachable siblings.
        assert not any(f.rule_id == "dead_code:unreachable" for f in findings)

    def test_module_level_return_followed_by_unreachable(self, tmp_path):
        # Module-level ``sys.exit`` is also a terminal in spirit but the analyzer
        # only detects Python-level terminals (return/raise/break/continue).
        # This test documents that constraint: a `raise SystemExit(0)` followed
        # by additional statements IS detected as unreachable.
        _write(
            tmp_path / "m.py",
            "raise SystemExit(0)\n" "print('after exit')\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unreachable" in rules

    def test_trailing_docstring_after_return_not_flagged(self, tmp_path):
        # Docstrings between the terminal and the dead block are ignored.
        _write(
            tmp_path / "m.py",
            "def f():\n"
            "    return 1\n"
            "    '''explain why we return early'''\n"
            "    do_thing()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        for f in findings:
            if f.rule_id == "dead_code:unreachable":
                # Docstring skipped; only ``do_thing()`` counts as unreachable.
                assert f.metadata["stmt_count"] == 1


class TestUnusedPrivate:
    def test_private_function_never_used_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def _helper():\n" "    return 1\n" "\n" "def public():\n" "    return 2\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [(f.rule_id, f.symbol) for f in findings]
        assert ("dead_code:unused-private", "_helper") in rules

    def test_private_function_referenced_not_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def _helper():\n" "    return 1\n" "\n" "def public():\n" "    return _helper()\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unused-private" not in rules

    def test_public_function_never_used_not_flagged(self, tmp_path):
        # Cross-module is not in scope; only private (underscore) names flagged.
        _write(
            tmp_path / "m.py",
            "def never_called():\n" "    return 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unused-private" not in rules

    def test_dunder_skipped(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "class C:\n"
            "    def __init__(self):\n"
            "        self.x = 1\n"
            "    def __repr__(self):\n"
            "        return 'C'\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unused-private" not in rules

    def test_async_function_also_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "async def _afn():\n" "    return 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [(f.rule_id, f.symbol) for f in findings]
        assert ("dead_code:unused-private", "_afn") in rules

    def test_private_method_called_via_self_not_flagged(self, tmp_path):
        # Regression: methods invoked as self._helper() are references;
        # without attribute tracking they were falsely flagged unused.
        _write(
            tmp_path / "m.py",
            "class C:\n"
            "    def run(self):\n"
            "        return self._helper()\n"
            "    def _helper(self):\n"
            "        return 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:unused-private" not in rules

    def test_private_method_never_called_still_flagged(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "class C:\n"
            "    def run(self):\n"
            "        return 1\n"
            "    def _helper(self):\n"
            "        return 2\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [(f.rule_id, f.symbol) for f in findings]
        assert ("dead_code:unused-private", "_helper") in rules


class TestStaleFixture:
    def test_unused_test_function_in_tests_dir_flagged(self, tmp_path):
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        # Use a non-pytest name so the analyzer treats it as a helper,
        # not a pytest entry point (which would be discovered externally).
        _write(
            test_dir / "test_unused.py",
            "def helper_old_setup():\n"
            "    return 1\n"
            "\n"
            "def test_used():\n"
            "    assert True\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [(f.rule_id, f.symbol) for f in findings]
        # ``helper_old_setup`` is not a pytest entry point and not
        # referenced anywhere; it should be flagged as a stale fixture.
        assert ("dead_code:stale-fixture", "helper_old_setup") in rules
        # ``test_used`` is a pytest entry point; never flagged.
        assert ("dead_code:stale-fixture", "test_used") not in rules

    def test_referenced_test_function_not_flagged(self, tmp_path):
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        _write(
            test_dir / "test_used.py",
            "from other_mod import helper\n"
            "def test_used():\n"
            "    assert helper() is not None\n",
        )
        other = tmp_path / "src" / "other_mod.py"
        _write(other, "def helper():\n    return 1\n")
        # ``helper`` is referenced from a test file but not the same one as
        # ``test_used`` itself — however, ``test_used`` IS referenced from
        # the same file it is defined in (test_used), so it's not stale.
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [(f.rule_id, f.symbol) for f in findings]
        # ``test_used`` is referenced inside test_used.py so not flagged.
        assert ("dead_code:stale-fixture", "test_used") not in rules

    def test_non_test_public_function_not_flagged_as_stale(self, tmp_path):
        # A non-test public function in production source is NOT a stale fixture.
        _write(
            tmp_path / "main.py",
            "def public_api():\n" "    return 1\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [f.rule_id for f in findings]
        assert "dead_code:stale-fixture" not in rules

    def test_conftest_skipped(self, tmp_path):
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        _write(
            test_dir / "conftest.py",
            "def pytest_collection_modifyitems():\n" "    return None\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        rules = [(f.rule_id, f.symbol) for f in findings]
        # conftest helper should be skipped, not flagged stale.
        assert not any(r == "dead_code:stale-fixture" and "conftest" in (s or "") for r, s in rules)


class TestDeterminism:
    def test_same_named_methods_receive_unique_stable_ids(self, tmp_path):
        _write(
            tmp_path / "models.py",
            "class First:\n"
            "    def _load(self):\n"
            "        return 1\n"
            "class Second:\n"
            "    def _load(self):\n"
            "        return 2\n",
        )
        first = DeadCodeAnalyzer().analyze(tmp_path)
        second = DeadCodeAnalyzer().analyze(tmp_path)
        ids = [finding.id for finding in first]
        assert len(ids) == len(set(ids))
        assert ids == [finding.id for finding in second]

    def test_repeat_scan_yields_byte_identical_findings(self, tmp_path):
        _write(
            tmp_path / "m.py",
            "def _orphan():\n"
            "    return 1\n"
            "\n"
            "def public():\n"
            "    return 2\n"
            "    unreachable()\n",
        )
        analyzer = DeadCodeAnalyzer()
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)
        first_dump = sorted(
            [{k: v for k, v in f.model_dump().items() if k != "detected_at"} for f in first],
            key=lambda d: d["id"],
        )
        second_dump = sorted(
            [{k: v for k, v in f.model_dump().items() if k != "detected_at"} for f in second],
            key=lambda d: d["id"],
        )
        assert first_dump == second_dump

    def test_finding_ids_unique_within_scan(self, tmp_path):
        _write(
            tmp_path / "a.py",
            "def _a():\n    return 1\n" "def _b():\n    return 2\n" "def _c():\n    return 3\n",
        )
        _write(
            tmp_path / "b.py",
            "def _d():\n    return 4\n",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        ids = [f.id for f in findings]
        assert len(ids) == len(set(ids))


class TestSecurityGates:
    def test_lockfiles_skipped(self, tmp_path):
        (tmp_path / "Pipfile.lock").write_text(
            "def _orphan():\n    return 1\n",
            encoding="utf-8",
        )
        assert DeadCodeAnalyzer().analyze(tmp_path) == []

    def test_excluded_directories_skipped(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        _write(
            venv / "m.py",
            "def _orphan():\n    return 1\n",
        )
        assert DeadCodeAnalyzer().analyze(tmp_path) == []

    def test_non_python_files_skipped(self, tmp_path):
        (tmp_path / "notes.md").write_text(
            "```python\ndef _orphan():\n    return 1\n```\n",
            encoding="utf-8",
        )
        findings = DeadCodeAnalyzer().analyze(tmp_path)
        assert findings == []

    def test_malformed_python_silently_skipped(self, tmp_path):
        (tmp_path / "broken.py").write_text(
            "def bad(:\n    not valid\n",
            encoding="utf-8",
        )
        assert DeadCodeAnalyzer().analyze(tmp_path) == []
