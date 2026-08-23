"""Tests for nesting_depth analyzer."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.analyzers.nesting_depth import (
    DEFAULT_NESTING_THRESHOLD,
    NestingDepthAnalyzer,
    _max_depth,
)
from app.models.finding import FindingSeverity


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


class TestNestingDepthAnalyzer:

    def test_simple_function_no_finding(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            def add(a, b):
                if a:
                    return a + b
                return b
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=DEFAULT_NESTING_THRESHOLD)
        assert analyzer.analyze(tmp_path) == []

    def test_function_at_threshold_no_finding(self, tmp_path):
        # depth = 4 (default threshold)
        _write(
            tmp_path / "m.py",
            """
            def f(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        assert analyzer.analyze(tmp_path) == []

    def test_function_above_threshold_warning(self, tmp_path):
        # depth = 5 → WARNING
        _write(
            tmp_path / "m.py",
            """
            def f(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == FindingSeverity.WARNING
        assert f.metadata["depth"] == 5
        assert f.metadata["threshold"] == 4
        assert f.analyzer == "nesting_depth"
        assert f.rule_id == "nesting_depth:over-threshold"
        assert f.symbol == "f"

    def test_very_deep_function_error(self, tmp_path):
        # depth = 9 → ERROR (>= 2*4). 9 nested ifs in a chain.
        src = (
            "def f(x):\n"
            "    if x:\n"
            "        if x:\n"
            "            if x:\n"
            "                if x:\n"
            "                    if x:\n"
            "                        if x:\n"
            "                            if x:\n"
            "                                if x:\n"
            "                                    return x\n"
            "    return 0\n"
        )
        _write(tmp_path / "m.py", src)

        analyzer = NestingDepthAnalyzer(threshold=4)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.ERROR

    def test_extreme_nesting_critical(self, tmp_path):
        # depth = 13 → CRITICAL (>= 3*4). Build a real nested chain.
        src = "def f(x):\n"
        for i in range(13):
            src += "    " * (i + 1) + "if x:\n"
        src += "    " * 14 + "return x\n"
        src += "    return 0\n"
        _write(tmp_path / "m.py", src)

        analyzer = NestingDepthAnalyzer(threshold=4)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.CRITICAL

    def test_class_method_detected(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            class C:
                def method(self, x):
                    if x:
                        if x > 0:
                            if x > 1:
                                if x > 2:
                                    if x > 3:
                                        return x
                    return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        assert findings[0].metadata["is_method"] is True
        assert "method" in findings[0].symbol

    def test_async_function_supported(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            async def afn(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        assert findings[0].symbol == "afn"
        assert findings[0].metadata["is_async"] is True

    def test_malformed_python_silently_skipped(self, tmp_path):
        (tmp_path / "broken.py").write_text(
            "def bad(:\n    not valid\n",
            encoding="utf-8",
        )
        analyzer = NestingDepthAnalyzer(threshold=1)
        assert analyzer.analyze(tmp_path) == []

    def test_ignored_file_extension_skipped(self, tmp_path):
        _write(tmp_path / "data.json", '{"x": 1}')
        analyzer = NestingDepthAnalyzer(threshold=1)
        assert analyzer.analyze(tmp_path) == []

    def test_lockfile_skipped(self, tmp_path):
        (tmp_path / "Pipfile.lock").write_text("def f():\n    pass\n", encoding="utf-8")
        analyzer = NestingDepthAnalyzer(threshold=1)
        assert analyzer.analyze(tmp_path) == []

    def test_python_file_in_excluded_directory_skipped(self, tmp_path):
        _write(
            tmp_path / ".venv" / "lib.py",
            """
            def f(x):
                if x:
                    if x:
                        if x:
                            return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=1)
        assert analyzer.analyze(tmp_path) == []

    def test_deterministic_finding_id(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            def f(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)
        ids_1 = sorted(f.id for f in first)
        ids_2 = sorted(f.id for f in second)
        assert ids_1 == ids_2
        assert len(ids_1) == 1

    def test_repeated_analysis_identical_payload(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            def f(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)

        def _strip_ts(findings):
            return [
                {k: v for k, v in f.model_dump().items() if k != "detected_at"}
                for f in findings
            ]

        assert _strip_ts(first) == _strip_ts(second)

    def test_multiple_functions_one_file(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            def low(x):
                if x:
                    return x
                return 0

            def high(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0
            """,
        )
        analyzer = NestingDepthAnalyzer(threshold=4)
        findings = analyzer.analyze(tmp_path)
        symbols = {f.symbol for f in findings}
        assert "low" not in symbols
        assert "high" in symbols
        assert len(findings) == 1

    def test_function_ordering_does_not_change_deterministic_output(self, tmp_path):
        body_a = """
            def alpha(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0

            def zeta(x):
                return x + 1
            """
        body_b = """
            def zeta(x):
                return x + 1

            def alpha(x):
                if x:
                    if x > 0:
                        if x > 1:
                            if x > 2:
                                if x > 3:
                                    return x
                return 0
            """
        _write(tmp_path / "a.py", body_a)
        _write(tmp_path / "b.py", body_b)

        analyzer = NestingDepthAnalyzer(threshold=4)
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)
        # Both files emit one alpha finding each; determinism preserved.
        alpha_first = [f for f in first if f.symbol == "alpha"]
        alpha_second = [f for f in second if f.symbol == "alpha"]
        assert len(alpha_first) == 2
        assert len(alpha_second) == 2
        assert sorted(f.id for f in first) == sorted(f.id for f in second)

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError):
            NestingDepthAnalyzer(threshold=0)
        with pytest.raises(ValueError):
            NestingDepthAnalyzer(threshold=-1)

    def test_empty_repository_returns_empty_list(self, tmp_path):
        analyzer = NestingDepthAnalyzer(threshold=DEFAULT_NESTING_THRESHOLD)
        assert analyzer.analyze(tmp_path) == []


class TestMaxDepthHelper:

    def test_flat_function(self):
        import ast as _ast
        tree = _ast.parse("def f():\n    return 1\n")
        func = tree.body[0]
        assert _max_depth(func) == 0

    def test_one_level_if(self):
        import ast as _ast
        tree = _ast.parse("def f(x):\n    if x:\n        return x\n    return 0\n")
        func = tree.body[0]
        assert _max_depth(func) == 1

    def test_loop_inside_if(self):
        import ast as _ast
        tree = _ast.parse(
            "def f(x):\n"
            "    if x:\n"
            "        for i in range(x):\n"
            "            return i\n"
            "    return 0\n"
        )
        func = tree.body[0]
        assert _max_depth(func) == 2
