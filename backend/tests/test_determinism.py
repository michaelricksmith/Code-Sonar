"""Cross-scan determinism regression tests.

These tests guard against accidental non-determinism in the analyzer
pipeline (e.g. UUID-based finding IDs, time-of-day seeds, glob-order
shuffles) by repeatedly scanning the same fixture repo and asserting
that score, finding count, debt total, and finding IDs are identical
across runs.

They run on a temporary repository fixture, not the user's working
tree, so they are safe to execute at any time.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.scoring.engine import calculate_score
from app.services.repository import scan_repository


def _build_fixture(root: Path) -> Path:
    (root / "small.py").write_text("x = 1\n", encoding="utf-8")
    (root / "markers.py").write_text(
        "# TODO: ship it\n# FIXME: later\n", encoding="utf-8"
    )
    (root / "complex_fn.py").write_text(
        "def f(x):\n"
        "    if x > 0:\n"
        "        if x > 1:\n"
        "            if x > 2:\n"
        "                if x > 3:\n"
        "                    return x\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return root


class TestScanDeterminism:

    def test_repeated_scans_yield_identical_findings(self):
        with tempfile.TemporaryDirectory() as t:
            repo = _build_fixture(Path(t))
            first = scan_repository(repo)
            second = scan_repository(repo)
            third = scan_repository(repo)

            ids_first = sorted(f.id for f in first)
            ids_second = sorted(f.id for f in second)
            ids_third = sorted(f.id for f in third)
            assert ids_first == ids_second == ids_third
            assert len(first) == len(second) == len(third)

    def test_repeated_scoring_yields_identical_score(self):
        with tempfile.TemporaryDirectory() as t:
            repo = _build_fixture(Path(t))
            findings = scan_repository(repo)
            r1 = calculate_score(findings)
            r2 = calculate_score(findings)
            r3 = calculate_score(findings)
            assert r1.score == r2.score == r3.score
            assert r1.grade == r2.grade == r3.grade
            assert r1.total_debt_points == r2.total_debt_points == r3.total_debt_points

    def test_finding_ids_contain_no_timestamp_components(self):
        with tempfile.TemporaryDirectory() as t:
            repo = _build_fixture(Path(t))
            findings = scan_repository(repo)
            for f in findings:
                # Every finding ID should be a stable hash; no wall-clock bytes.
                assert "T" not in f.id or ":" not in f.id
                assert "-" not in f.id.replace("finding_", "").replace(
                    "oversized_files_", ""
                ).replace("oversized_functions_", "").replace(
                    "comment_markers_", ""
                ).replace("cyclomatic_complexity_", "").replace(
                    "nesting_depth_", ""
                ).replace("testing_debt_", "")

    def test_finding_ids_stable_across_pipeline_runs(self):
        with tempfile.TemporaryDirectory() as t:
            repo = _build_fixture(Path(t))
            a = scan_repository(repo)
            # Re-analyze multiple times with different findings dict orders.
            b = sorted(scan_repository(repo), key=lambda f: f.id)
            c = sorted(scan_repository(repo), key=lambda f: f.file_path)
            ids_a = sorted(f.id for f in a)
            ids_b = sorted(f.id for f in b)
            ids_c = sorted(f.id for f in c)
            assert ids_a == ids_b == ids_c
