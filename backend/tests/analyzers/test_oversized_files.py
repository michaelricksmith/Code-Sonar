"""Tests for oversized_files analyzer.

Verifies:
- Files below threshold produce no findings.
- Files exactly at threshold produce no findings.
- Files above threshold produce normalized findings with correct
  severity, line count, threshold, and debt points.
- Excluded directories / binary files are skipped.
- Finding IDs are deterministic across repeated runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analyzers.oversized_files import (
    DEFAULT_THRESHOLD,
    OversizedFilesAnalyzer,
)
from app.models.finding import FindingCategory, FindingSeverity


class TestOversizedFilesAnalyzer:
    def test_file_below_threshold_no_finding(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        paths = {Path(f.file_path).name for f in findings}
        assert "small.py" not in paths
        assert "notes.md" not in paths

    def test_file_exactly_at_threshold_no_finding(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        exact = [f for f in findings if Path(f.file_path).name == "exact.py"]
        assert exact == [], "File at threshold must not produce a finding"

    def test_file_above_threshold_emits_warning(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        big = next(
            (f for f in findings if Path(f.file_path).name == "big.py"), None
        )
        assert big is not None, "big.py (501 lines) must produce a finding"
        assert big.severity == FindingSeverity.WARNING
        assert big.category == FindingCategory.MAINTAINABILITY
        assert big.analyzer == "oversized_files"
        assert big.rule_id == "oversized_files:over-threshold"
        assert big.metadata["line_count"] == 501
        assert big.metadata["threshold"] == threshold
        assert f"line_count=501" in big.evidence
        assert f"threshold={threshold}" in big.evidence
        assert big.debt_points > 0
        assert big.suggestion

    def test_2x_threshold_emits_error(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        huge = next(
            (f for f in findings if Path(f.file_path).name == "huge.py"), None
        )
        assert huge is not None
        assert huge.severity == FindingSeverity.ERROR
        assert huge.metadata["line_count"] == 1000

    def test_3x_threshold_emits_critical(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        massive = next(
            (f for f in findings if Path(f.file_path).name == "massive.py"), None
        )
        assert massive is not None
        assert massive.severity == FindingSeverity.CRITICAL
        assert massive.metadata["line_count"] == 1500

    def test_excluded_directories_skipped(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        paths = {f.file_path for f in findings}
        assert not any(".venv" in p for p in paths)
        assert not any("node_modules" in p for p in paths)
        assert not any(p.startswith("build/") or "/build/" in p for p in paths)

    def test_binary_files_skipped(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        findings = analyzer.analyze(mixed_repo)
        assert all(not f.file_path.endswith(".png") for f in findings)

    def test_deterministic_finding_id(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        first = analyzer.analyze(mixed_repo)
        second = analyzer.analyze(mixed_repo)
        ids_1 = sorted(f.id for f in first)
        ids_2 = sorted(f.id for f in second)
        assert ids_1 == ids_2, "Finding IDs must be deterministic across scans"

    def test_finding_id_stable_across_re_analyzers(self, mixed_repo):
        a = OversizedFilesAnalyzer(threshold=DEFAULT_THRESHOLD)
        b = OversizedFilesAnalyzer(threshold=DEFAULT_THRESHOLD)
        ids_a = {f.id for f in a.analyze(mixed_repo)}
        ids_b = {f.id for f in b.analyze(mixed_repo)}
        assert ids_a == ids_b

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError):
            OversizedFilesAnalyzer(threshold=0)
        with pytest.raises(ValueError):
            OversizedFilesAnalyzer(threshold=-1)

    def test_empty_repository_returns_empty_list(self, tmp_path):
        analyzer = OversizedFilesAnalyzer(threshold=DEFAULT_THRESHOLD)
        assert analyzer.analyze(tmp_path) == []

    def test_finding_payload_matches_finding_schema(self, mixed_repo, threshold):
        analyzer = OversizedFilesAnalyzer(threshold=threshold)
        for f in analyzer.analyze(mixed_repo):
            assert 0.0 <= f.confidence <= 1.0
            assert f.file_path
            assert f.message
            assert f.evidence
            assert f.debt_points >= 0
            assert f.analyzer == "oversized_files"
