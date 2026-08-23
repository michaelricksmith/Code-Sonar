"""Shared determinism helpers for analyzer and scoring tests.

These helpers are the project's single source of truth for
determinism invariants. Every analyzer test that produces findings
should call one or more of these helpers to guarantee:

1. Repeated scans of the same repository produce byte-identical
   finding payloads (modulo the ``detected_at`` timestamp, which is
   already excluded from the deterministic contract).
2. Finding IDs are unique within a single scan.
3. Finding ordering is stable across repeated scans.
4. The scoring engine is deterministic: same findings -> same
   score, grade, and per-category breakdown.
5. Source-vs-fixture classification is consistent for any given
   relative path.

Any change to these helpers is a cross-cutting change to the
regression suite. Update the per-analyzer tests accordingly.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from app.models.finding import Finding
from app.scoring.engine import ScoringResult, calculate_score
from app.security.path_classifier import classify_path
from app.services.repository import scan_repository

# ---------------------------------------------------------------------------
# Finding-payload helpers
# ---------------------------------------------------------------------------


def strip_detected_at(findings: list[Finding]) -> list[dict[str, Any]]:
    """Return findings as JSON-ready dicts with ``detected_at`` removed.

    Pydantic v2 ``model_dump()`` produces nested dicts (e.g. for the
    ``metadata`` field). ``json.dumps`` with ``default=str`` is used
    for byte-identical comparison so any pydantic custom types (e.g.
    enums) serialize deterministically.
    """
    return [
        {k: v for k, v in f.model_dump().items() if k != "detected_at"}
        for f in findings
    ]


def payloads_equal(a: list[Finding], b: list[Finding]) -> bool:
    """True if two finding lists have byte-identical payloads (sans timestamp)."""
    sa = sorted(strip_detected_at(a), key=lambda d: d["id"])
    sb = sorted(strip_detected_at(b), key=lambda d: d["id"])
    return json.dumps(sa, default=str) == json.dumps(sb, default=str)


def finding_ids(findings: list[Finding]) -> list[str]:
    return sorted(f.id for f in findings)


# ---------------------------------------------------------------------------
# Analyzer determinism
# ---------------------------------------------------------------------------


def assert_byte_identical_repeated_scan(
    analyzer: object,
    repo_path: Path,
    *,
    runs: int = 3,
) -> list[Finding]:
    """Run ``analyzer.analyze(repo_path)`` ``runs`` times; assert byte-identical.

    Returns the findings from the first run so the caller can do
    additional assertions on the result.
    """
    results: list[list[Finding]] = []
    for _ in range(runs):
        results.append(analyzer.analyze(repo_path))
    first = results[0]
    for nxt in results[1:]:
        assert payloads_equal(first, nxt), (
            f"Analyzer {type(analyzer).__name__} produced non-byte-identical "
            f"findings across {runs} scans of {repo_path}"
        )
    return first


def assert_unique_finding_ids(findings: list[Finding]) -> None:
    """Assert that no two findings in a single scan share an id."""
    ids = [f.id for f in findings]
    duplicates = {x for x in ids if ids.count(x) > 1}
    assert not duplicates, (
        f"Duplicate finding IDs within a single scan: {sorted(duplicates)}"
    )


def assert_stable_id_set_across_runs(
    analyzer: object, repo_path: Path, *, runs: int = 3
) -> list[str]:
    """Assert finding IDs are the same set across repeated scans."""
    id_sets: list[set[str]] = []
    for _ in range(runs):
        id_sets.append({f.id for f in analyzer.analyze(repo_path)})
    first = id_sets[0]
    for nxt in id_sets[1:]:
        assert first == nxt, (
            f"Analyzer {type(analyzer).__name__} produced different ID sets "
            f"across {runs} scans of {repo_path}"
        )
    return sorted(first)


def assert_no_duplicate_finding_ids_in_pipeline(repo_path: Path) -> None:
    """Run the full pipeline against ``repo_path`` and assert no duplicate IDs."""
    findings = scan_repository(repo_path)
    assert_unique_finding_ids(findings)


# ---------------------------------------------------------------------------
# Scoring determinism
# ---------------------------------------------------------------------------


def assert_scoring_determinism(
    findings: list[Finding], *, runs: int = 5
) -> ScoringResult:
    """Assert that repeated scoring of the same findings yields identical output."""
    results: list[ScoringResult] = [
        calculate_score(findings) for _ in range(runs)
    ]
    first = results[0]
    for nxt in results[1:]:
        assert first.score == nxt.score
        assert first.grade == nxt.grade
        assert first.total_debt_points == nxt.total_debt_points
        assert first.finding_count == nxt.finding_count
        assert first.findings_source_breakdown == nxt.findings_source_breakdown
        assert first.to_dict() == nxt.to_dict()
    return first


def assert_score_input_order_irrelevant(findings: list[Finding]) -> ScoringResult:
    """Assert scoring ignores input order (re-reordering shouldn't change score)."""
    r1 = calculate_score(findings)
    r2 = calculate_score(list(reversed(findings)))
    r3 = calculate_score(sorted(findings, key=lambda f: f.id))
    r4 = calculate_score(sorted(findings, key=lambda f: f.file_path))
    assert r1.score == r2.score == r3.score == r4.score
    assert r1.grade == r2.grade == r3.grade == r4.grade
    assert (
        r1.total_debt_points
        == r2.total_debt_points
        == r3.total_debt_points
        == r4.total_debt_points
    )
    return r1


# ---------------------------------------------------------------------------
# Source-vs-fixture classification
# ---------------------------------------------------------------------------


def assert_classification_consistency(rel_paths: list[str]) -> None:
    """classify_path() must be a pure function: same input -> same output.

    Callers can use this to lock in that path classification has not
    been changed by accident across releases.
    """
    for rel in rel_paths:
        cls1 = classify_path(rel)
        cls2 = classify_path(rel)
        assert cls1 == cls2, (
            f"classify_path({rel!r}) is non-deterministic: {cls1} vs {cls2}"
        )


# ---------------------------------------------------------------------------
# End-to-end pipeline determinism
# ---------------------------------------------------------------------------


def assert_full_pipeline_byte_identical_repeated_scan(
    repo_path: Path, *, runs: int = 3
) -> list[Finding]:
    """Run the entire pipeline ``runs`` times; assert byte-identical findings."""
    results: list[list[Finding]] = []
    for _ in range(runs):
        results.append(scan_repository(repo_path))
    first = results[0]
    for nxt in results[1:]:
        assert payloads_equal(first, nxt), (
            f"Full pipeline produced non-byte-identical findings across {runs} "
            f"scans of {repo_path}"
        )
    return first


# ---------------------------------------------------------------------------
# Temp-fixture helpers
# ---------------------------------------------------------------------------


def make_temp_repo(files: dict[str, str]) -> Path:
    """Build a temporary repository with the given ``{rel_path: content}``.

    Returns the repo root path. The directory persists until the caller
    removes it; use a ``tempfile.TemporaryDirectory`` context if you
    need automatic cleanup.
    """
    tmp = Path(tempfile.mkdtemp(prefix="codesonar-det-"))
    for rel, content in files.items():
        fp = tmp / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return tmp
