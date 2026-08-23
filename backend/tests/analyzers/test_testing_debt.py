"""Tests for testing_debt analyzer."""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.analyzers.testing_debt import TestingDebtAnalyzer


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


class TestTestingDebtAnalyzer:

    def test_untested_module_emits_finding(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        analyzer = TestingDebtAnalyzer()
        findings = analyzer.analyze(tmp_path)
        symbols = {f.rule_id for f in findings}
        assert "testing_debt:untested-module" in symbols

    def test_tested_module_no_finding(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        _write(tmp_path / "tests" / "test_m.py", "from m import f\n")
        analyzer = TestingDebtAnalyzer()
        findings = analyzer.analyze(tmp_path)
        assert findings == []

    def test_suffix_test_also_counts(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        _write(tmp_path / "tests" / "m_test.py", "from m import f\n")
        analyzer = TestingDebtAnalyzer()
        assert analyzer.analyze(tmp_path) == []

    def test_missing_tests_dir_emits_repo_finding(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        analyzer = TestingDebtAnalyzer()
        findings = analyzer.analyze(tmp_path)
        rule_ids = {f.rule_id for f in findings}
        assert "testing_debt:missing-tests-dir" in rule_ids

    def test_empty_repo_no_findings(self, tmp_path):
        analyzer = TestingDebtAnalyzer()
        assert analyzer.analyze(tmp_path) == []

    def test_excluded_directories_skipped(self, tmp_path):
        _write(tmp_path / ".venv" / "lib.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        analyzer = TestingDebtAnalyzer()
        findings = analyzer.analyze(tmp_path)
        assert findings == []

    def test_lockfile_skipped(self, tmp_path):
        # Even with a .py suffix, lockfile names are skipped.
        (tmp_path / "Pipfile.lock").write_text("def f():\n    pass\n", encoding="utf-8")
        _write(tmp_path / "tests" / "__init__.py", "")
        analyzer = TestingDebtAnalyzer()
        # Only the missing-tests-dir rule would fire if there are no tests.
        # But the lockfile should not produce an untested-module finding.
        findings = analyzer.analyze(tmp_path)
        assert all("Pipfile.lock" not in f.file_path for f in findings)

    def test_severity_scales_with_module_size(self, tmp_path):
        # 50 lines -> WARNING
        small = "\n".join(f"x_{i} = {i}" for i in range(50))
        _write(tmp_path / "small.py", f"x = 1\n{small}\n")
        _write(tmp_path / "tests" / "__init__.py", "")

        # 200 lines -> ERROR
        big = "\n".join(f"x_{i} = {i}" for i in range(200))
        _write(tmp_path / "big.py", f"x = 1\n{big}\n")

        # 400 lines -> CRITICAL
        huge = "\n".join(f"x_{i} = {i}" for i in range(400))
        _write(tmp_path / "huge.py", f"x = 1\n{huge}\n")

        analyzer = TestingDebtAnalyzer()
        findings = analyzer.analyze(tmp_path)
        by_module = {f.file_path: f for f in findings}
        assert by_module["small.py"].severity.value == "warning"
        assert by_module["big.py"].severity.value == "error"
        assert by_module["huge.py"].severity.value == "critical"

    def test_deterministic_finding_id(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        analyzer = TestingDebtAnalyzer()
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)
        assert sorted(f.id for f in first) == sorted(f.id for f in second)

    def test_repeated_analysis_identical_payload(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        analyzer = TestingDebtAnalyzer()
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)

        def _strip_ts(findings):
            return [
                {k: v for k, v in f.model_dump().items() if k != "detected_at"}
                for f in findings
            ]
        assert _strip_ts(first) == _strip_ts(second)

    def test_init_files_in_tests_dir_count_as_test_dir(self, tmp_path):
        _write(tmp_path / "m.py", "def f():\n    return 1\n")
        _write(tmp_path / "tests" / "__init__.py", "")
        # No actual test_m.py — should still be flagged as untested.
        analyzer = TestingDebtAnalyzer()
        findings = analyzer.analyze(tmp_path)
        rule_ids = {f.rule_id for f in findings}
        assert "testing_debt:untested-module" in rule_ids
        assert "testing_debt:missing-tests-dir" not in rule_ids

    def test_threshold_property_is_none(self):
        analyzer = TestingDebtAnalyzer()
        assert analyzer.threshold is None

    def test_name_property(self):
        assert TestingDebtAnalyzer().name == "testing_debt"
