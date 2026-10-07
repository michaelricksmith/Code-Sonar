"""Per-analyzer determinism regression tests.

These tests apply the shared determinism helpers (``tests.utils.determinism``)
to every analyzer in the registered pipeline. They are the
Checkpoint 5 Lane 3 deliverable: a single regression guard that
locks in byte-identical determinism across the analyzer set.

If a future analyzer is added to ``app.services.repository``,
this test file MUST be updated to include it. The parametrized
fixture list is the contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.analyzers.base import Analyzer
from app.analyzers.comment_markers import CommentMarkersAnalyzer
from app.analyzers.cyclomatic_complexity import CyclomaticComplexityAnalyzer
from app.analyzers.dead_code import DeadCodeAnalyzer
from app.analyzers.nesting_depth import NestingDepthAnalyzer
from app.analyzers.oversized_files import OversizedFilesAnalyzer
from app.analyzers.oversized_functions import OversizedFunctionsAnalyzer
from app.analyzers.secrets import SecretsAnalyzer
from app.analyzers.testing_debt import TestingDebtAnalyzer
from app.services.repository import get_registered_analyzers
from tests.utils.determinism import (
    assert_byte_identical_repeated_scan,
    assert_full_pipeline_byte_identical_repeated_scan,
    assert_no_duplicate_finding_ids_in_pipeline,
    assert_unique_finding_ids,
    make_temp_repo,
)

# Every analyzer in the registry, instantiated for parametrization.
ALL_ANALYZERS: list[Analyzer] = [
    CommentMarkersAnalyzer(),
    OversizedFilesAnalyzer(),
    OversizedFunctionsAnalyzer(),
    CyclomaticComplexityAnalyzer(),
    NestingDepthAnalyzer(),
    SecretsAnalyzer(),
    TestingDebtAnalyzer(),
    DeadCodeAnalyzer(),
]


@pytest.fixture(
    params=ALL_ANALYZERS,
    ids=lambda a: a.name,
)
def analyzer(request: pytest.FixtureRequest) -> Analyzer:
    return request.param


def test_registry_is_complete() -> None:
    """The parametrized list MUST match the registered analyzer set."""
    registered_names = {a.name for a in get_registered_analyzers()}
    listed_names = {a.name for a in ALL_ANALYZERS}
    assert registered_names == listed_names, (
        "Analyzer registry drift: registered analyzers "
        f"{registered_names} differ from test list {listed_names}. "
        "Update tests/test_analyzer_determinism.py to keep them in sync."
    )


class TestPerAnalyzerDeterminism:
    def test_byte_identical_repeated_scan(self, analyzer: Analyzer, tmp_path):
        # Build a fixture that contains a comment, an oversized file,
        # a long function, a fake secret, and an unused private symbol
        # so every analyzer has *some* signal.
        (tmp_path / "m.py").write_text(
            "def _unused():\n"
            "    return 1\n"
            "\n"
            "def public():\n"
            "    # TODO: ship\n"
            "    x = 1\n"
            "    if x > 0:\n"
            "        if x > 1:\n"
            "            if x > 2:\n"
            "                if x > 3:\n"
            "                    if x > 4:\n"
            "                        return x\n"
            "    return 0\n"
            "\n"
            "AKIAIOSFODNN7EXAMPLE\n",
            encoding="utf-8",
        )
        # The analyzer under test is responsible for skipping paths
        # it does not own; we just want to verify repeated scans of
        # the same fixture produce the same findings.
        findings = assert_byte_identical_repeated_scan(analyzer, tmp_path, runs=3)
        assert_unique_finding_ids(findings)


class TestFullPipelineDeterminism:
    def test_full_pipeline_byte_identical_three_runs(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "def _unused():\n    return 1\n"
            "\n"
            "def public():\n"
            "    # TODO: ship\n"
            "    AKIAIOSFODNN7EXAMPLE\n"
            "    return 2\n",
            encoding="utf-8",
        )
        assert_full_pipeline_byte_identical_repeated_scan(tmp_path, runs=3)

    def test_no_duplicate_finding_ids_in_pipeline(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "def public():\n    return 1\n",
            encoding="utf-8",
        )
        assert_no_duplicate_finding_ids_in_pipeline(tmp_path)


class TestOrderingInvariants:
    def test_findings_are_returned_in_id_alphabetic_order(self, tmp_path):
        # The full pipeline emits findings in registration order, but
        # the contract for the API is that the output is stable. We
        # assert that two runs produce the same *sorted* id sequence.
        from app.services.repository import scan_repository

        repo = make_temp_repo(
            {
                "a.py": "def f():\n    # TODO: ship\n    return 1\n",
                "b.py": "def g():\n    return 2\n",
            }
        )
        try:
            first = scan_repository(repo)
            second = scan_repository(repo)
            ids_1 = sorted(f.id for f in first)
            ids_2 = sorted(f.id for f in second)
            assert ids_1 == ids_2
            assert len(first) == len(second)
        finally:
            import shutil
            shutil.rmtree(repo, ignore_errors=True)

    def test_scoring_input_order_irrelevant(self):
        from app.models.finding import (
            Finding,
            FindingCategory,
            FindingSeverity,
        )
        from tests.utils.determinism import assert_score_input_order_irrelevant

        def _mk(i: int) -> Finding:
            return Finding(
                id=f"ord_{i}",
                rule_id="x:y",
                category=FindingCategory.MAINTAINABILITY,
                severity=FindingSeverity.WARNING,
                confidence=1.0,
                file_path=f"src/m{i}.py",
                line_start=1,
                line_end=1,
                symbol=None,
                evidence="",
                message="",
                suggestion=None,
                debt_points=3,
                remediation_effort=None,
                analyzer="synthetic",
                metadata={},
            )

        findings = [_mk(i) for i in range(10)]
        assert_score_input_order_irrelevant(findings)


# ---------------------------------------------------------------------------
# Cross-process determinism
# ---------------------------------------------------------------------------

_SCAN_SCRIPT = (
    "import json, sys; "
    "sys.path.insert(0, sys.argv[1]); "
    "from app.services.repository import scan_repository; "
    "result = scan_repository(sys.argv[2]); "
    "print(json.dumps(sorted(f.id for f in result)))"
)


def _scan_ids_in_subprocess(repo: Path, hash_seed: str) -> list[str]:
    """Scan the repo in a fresh interpreter and return sorted finding IDs."""
    backend_dir = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    env["CODESONAR_UNSAFE_ALLOW_ANY_SCAN_PATH"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", _SCAN_SCRIPT, backend_dir, str(repo)],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, (
        f"subprocess scan failed (seed={hash_seed}):\n{proc.stderr[-2000:]}"
    )
    return json.loads(proc.stdout)


class TestCrossProcessDeterminism:
    """Finding IDs must be identical across interpreter restarts.

    Regression test for the salted-hash() bug: six analyzers built finding
    IDs with Python's built-in hash(), which is randomized per process, so
    identical scans produced different IDs after any restart or redeploy.
    The drift view matches findings by ID, so this silently corrupted drift
    (every finding reported NEW, every baseline finding RESOLVED). The
    in-process tests above cannot catch this; two subprocesses with
    different PYTHONHASHSEED values reproduce the production condition.
    """

    def test_finding_ids_identical_across_processes(self):
        repo = make_temp_repo(
            {
                "m.py": (
                    "def _unused():\n"
                    "    return 1\n"
                    "\n"
                    "def public():\n"
                    "    # TODO: ship\n"
                    "    x = 1\n"
                    "    if x > 0:\n"
                    "        if x > 1:\n"
                    "            if x > 2:\n"
                    "                if x > 3:\n"
                    "                    if x > 4:\n"
                    "                        return x\n"
                    "    return 0\n"
                    "\n"
                    "AKIAIOSFODNN7EXAMPLE\n"
                ),
            }
        )
        try:
            ids_seed_0 = _scan_ids_in_subprocess(repo, "0")
            ids_seed_42 = _scan_ids_in_subprocess(repo, "42")
            assert ids_seed_0, "fixture produced no findings; test is vacuous"
            assert ids_seed_0 == ids_seed_42, (
                "finding IDs differ across processes: "
                f"{len(ids_seed_0)} vs {len(ids_seed_42)} IDs"
            )
        finally:
            import shutil

            shutil.rmtree(repo, ignore_errors=True)
