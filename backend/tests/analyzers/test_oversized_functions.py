"""Tests for oversized_functions analyzer.

Verifies:
- Python AST-based detection (no regex).
- Functions/async/methods/nested all detected.
- Severity scales with how far the function exceeds the threshold.
- Deterministic finding IDs.
- Files below or at the threshold produce no findings.
- Lockfiles, binary files, and excluded directories are ignored.
- Malformed Python sources are silently skipped.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.analyzers.oversized_functions import (
    DEFAULT_FUNCTION_THRESHOLD,
    OversizedFunctionsAnalyzer,
)
from app.models.finding import FindingCategory, FindingSeverity


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


class TestOversizedFunctionsAnalyzer:

    def test_short_function_no_finding(self, tmp_path):
        _write(
            tmp_path / "m.py",
            """
            def small():
                return 1
            """,
        )
        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        assert analyzer.analyze(tmp_path) == []

    def test_exactly_at_threshold_no_finding(self, tmp_path):
        body_lines = ["def exact():"]
        # Threshold lines total, including the def line.
        for i in range(49):
            body_lines.append(f"    x_{i} = {i}")
        body_lines.append("    return x_0")
        # Add a trailing blank line so the AST reports end_lineno == 51
        # but the analyzer measures exactly 50 lines from def to return.
        body_lines.append("")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=51)
        assert analyzer.analyze(tmp_path) == []

    def test_above_threshold_emits_warning(self, tmp_path):
        body_lines = ["def over():", "    # filler"]
        for i in range(60):
            body_lines.append(f"    x_{i} = {i}")
        body_lines.append("    return x_0")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity in (
            FindingSeverity.WARNING,
            FindingSeverity.ERROR,
            FindingSeverity.CRITICAL,
        )
        assert f.category == FindingCategory.MAINTAINABILITY
        assert f.analyzer == "oversized_functions"
        assert f.rule_id == "oversized_functions:over-threshold"
        assert f.symbol == "over"
        assert f.metadata["function_length"] > 50
        assert f.metadata["threshold"] == 50
        assert f.metadata["is_async"] is False
        assert f.metadata["is_method"] is False
        assert "over" in f.evidence
        assert "threshold=50" in f.evidence
        assert f.suggestion
        assert f.debt_points > 0

    def test_very_large_function_emits_critical(self, tmp_path):
        body_lines = ["def huge():", "    # filler"]
        for i in range(200):
            body_lines.append(f"    x_{i} = {i}")
        body_lines.append("    return x_0")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.CRITICAL
        assert findings[0].metadata["function_length"] >= 150

    def test_async_function_is_detected(self, tmp_path):
        body_lines = ["async def afn():", "    a = 1"]
        for i in range(60):
            body_lines.append(f"    x_{i} = {i}")
        body_lines.append("    return x_0")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        assert findings[0].metadata["is_async"] is True
        assert findings[0].symbol == "afn"

    def test_method_inside_class_is_detected(self, tmp_path):
        body_lines = ["class C:", "    def method(self):", "        x = 1"]
        for i in range(80):
            body_lines.append(f"        x_{i} = {i}")
        body_lines.append("        return x_0")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        findings = analyzer.analyze(tmp_path)
        assert len(findings) == 1
        f = findings[0]
        assert f.metadata["is_method"] is True
        assert f.symbol == "C.method"

    def test_nested_function_detected_and_qualified(self, tmp_path):
        # Build a fixture where a module-level `outer` helper hosts a
        # large nested `inner` function. The test asserts that, when a
        # nested function exceeds the threshold, its emitted symbol is
        # the fully-qualified `outer.inner` rather than plain `inner`.
        body = []
        body += [
            "def outer():",
            "    def inner():",
            "        # filler",
        ]
        for i in range(80):
            body.append(f"        z_{i} = {i}")
        body += [
            "        return 0",
            "    return inner",
            "",
            "outer()",
        ]
        _write(tmp_path / "m.py", "\n".join(body) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        findings = analyzer.analyze(tmp_path)

        # Inner must appear under its fully-qualified name.
        symbols = {f.symbol for f in findings}
        assert "outer.inner" in symbols, sorted(symbols)

        # Any finding whose symbol begins with `outer` must be the
        # qualified one: there must be no unqualified `inner` finding.
        assert "inner" not in symbols, sorted(symbols)

    def test_malformed_python_silently_skipped(self, tmp_path):
        (tmp_path / "broken.py").write_text(
            "def bad(:\n    not valid python\n",
            encoding="utf-8",
        )
        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        findings = analyzer.analyze(tmp_path)
        assert findings == []

    def test_ignored_file_extension_skipped(self, tmp_path):
        _write(
            tmp_path / "data.json",
            '{"x": 1}',
        )
        _write(
            tmp_path / "code.py",
            "\n".join(["def f():", "    pass"] + ["    pass"] * 5),
        )
        analyzer = OversizedFunctionsAnalyzer(threshold=5)
        findings = analyzer.analyze(tmp_path)
        assert all("data.json" not in f.file_path for f in findings)

    def test_lockfile_skipped_even_if_named_like_py(self, tmp_path):
        # filename-specific gate catches lockfiles even if extension were .py.
        lock = tmp_path / "Pipfile.lock"
        lock.write_text("\n".join(f"  x_{i} = {i}" for i in range(200)),
                         encoding="utf-8")
        analyzer = OversizedFunctionsAnalyzer(threshold=10)
        assert analyzer.analyze(tmp_path) == []

    def test_python_file_in_excluded_directory_skipped(self, tmp_path):
        _write(
            tmp_path / ".venv" / "lib.py",
            "def f():\n    pass\n",
        )
        analyzer = OversizedFunctionsAnalyzer(threshold=5)
        assert analyzer.analyze(tmp_path) == []

    def test_deterministic_finding_id(self, tmp_path):
        body_lines = ["def fn():", "    x = 1"]
        for i in range(70):
            body_lines.append(f"    y_{i} = {i}")
        body_lines.append("    return x")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)
        ids_1 = sorted(f.id for f in first)
        ids_2 = sorted(f.id for f in second)
        assert ids_1 == ids_2

    def test_repeat_analysis_identical_payload(self, tmp_path):
        body_lines = ["def fn():", "    x = 1"]
        for i in range(70):
            body_lines.append(f"    y_{i} = {i}")
        body_lines.append("    return x")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        first = analyzer.analyze(tmp_path)
        second = analyzer.analyze(tmp_path)

        def _strip_ts(findings):
            return [
                {k: v for k, v in f.model_dump().items() if k != "detected_at"}
                for f in findings
            ]

        assert _strip_ts(first) == _strip_ts(second), (
            "Finding payloads must be identical except for detected_at"
        )

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError):
            OversizedFunctionsAnalyzer(threshold=0)
        with pytest.raises(ValueError):
            OversizedFunctionsAnalyzer(threshold=-1)

    def test_empty_repository_no_findings(self, tmp_path):
        analyzer = OversizedFunctionsAnalyzer(threshold=DEFAULT_FUNCTION_THRESHOLD)
        assert analyzer.analyze(tmp_path) == []

    def test_finding_payload_validates(self, tmp_path):
        body_lines = ["def fn():", "    x = 1"]
        for i in range(80):
            body_lines.append(f"    z_{i} = {i}")
        body_lines.append("    return x")
        _write(tmp_path / "m.py", "\n".join(body_lines) + "\n")

        analyzer = OversizedFunctionsAnalyzer(threshold=50)
        for f in analyzer.analyze(tmp_path):
            assert 0.0 <= f.confidence <= 1.0
            assert f.line_end >= f.line_start
            assert f.file_path
            assert f.message
            assert f.analyzer == "oversized_functions"
