"""Tests for remediation outcome records and persistence."""

from pathlib import Path

import pytest

from app.ml.outcomes import JsonlOutcomeStore, RemediationOutcome


def _outcome(outcome_id: str = "outcome-1") -> RemediationOutcome:
    return RemediationOutcome(
        outcome_id=outcome_id,
        repository_id="repo-1",
        finding_id="finding-1",
        before_scan_id="scan-before",
        after_scan_id="scan-after",
        attempted_at="2026-08-30T20:30:00+00:00",
        executor="cursor",
        remediation_kind="automated_patch",
        build_passed=True,
        tests_passed=True,
        finding_resolved=True,
        score_delta=18,
        debt_points_delta=-12,
    )


def test_successful_outcome_requires_resolution_and_no_regression() -> None:
    assert _outcome().successful is True

    failed = RemediationOutcome(
        outcome_id="outcome-2",
        repository_id="repo-1",
        finding_id="finding-1",
        before_scan_id="scan-before",
        after_scan_id="scan-after",
        attempted_at="2026-08-30T20:31:00+00:00",
        executor="cursor",
        remediation_kind="automated_patch",
        build_passed=True,
        tests_passed=True,
        finding_resolved=True,
        regression_detected=True,
        score_delta=18,
        debt_points_delta=-12,
    )
    assert failed.successful is False


def test_jsonl_store_round_trips_and_filters_repository(tmp_path: Path) -> None:
    store = JsonlOutcomeStore(tmp_path / "outcomes.jsonl")
    store.append(_outcome("outcome-2"))
    store.append(
        RemediationOutcome(
            outcome_id="outcome-1",
            repository_id="repo-2",
            finding_id="finding-2",
            before_scan_id="scan-a",
            after_scan_id="scan-b",
            attempted_at="2026-08-30T20:20:00+00:00",
            executor="human",
            remediation_kind="manual_patch",
            build_passed=None,
            tests_passed=True,
            finding_resolved=False,
        )
    )

    assert [item.outcome_id for item in store.load_all()] == ["outcome-1", "outcome-2"]
    assert [item.outcome_id for item in store.load_all("repo-1")] == ["outcome-2"]
    loaded = store.get("outcome-2")
    assert loaded is not None
    assert loaded.score_delta == 18
    assert loaded.debt_points_delta == -12
    assert loaded.successful is True


def test_store_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "outcomes.jsonl"
    path.write_text(
        '{"outcome_schema_version":"99","outcome_id":"bad"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid remediation outcome at line 1"):
        JsonlOutcomeStore(path).load_all()
