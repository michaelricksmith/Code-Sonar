from __future__ import annotations

import pytest

from app.calibration.capture import capture_frozen_scan
from app.calibration.contracts import CONTRACT_VERSION, REVIEW_PACKET_VERSION
from app.calibration.pilot import (
    load_finalized_independent_labels,
    make_adjudication_packet,
    make_review_packet,
    stratified_finding_sample,
    validate_pilot_manifest,
)
from app.calibration.validation import EvidenceValidationError


def _metadata() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "artifact_type": "repository_metadata",
        "case_id": "csb-001",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "strata": {"size": "small", "shape": "library", "profile": "mixed"},
    }


def _scan() -> dict[str, object]:
    raw = {
        "scoring_version": "1.0",
        "analyzer_execution": [
            {"analyzer": "complexity", "status": "completed", "finding_count": 4}
        ],
        "score": 700,
        "grade": "B",
        "findings": [
            {
                "id": f"finding-{index}",
                "analyzer": "complexity",
                "severity": severity,
                "category": "complexity",
            }
            for index, severity in enumerate(("warning", "warning", "warning", "error"))
        ],
    }
    return capture_frozen_scan(
        raw,
        case_id="csb-001",
        analyzer_versions={"complexity": "1"},
        expected_scoring_version="1.0",
    )


def _label(reviewer: str, grade: str) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "artifact_type": "expert_label",
        "case_id": "csb-001",
        "reviewer_id": reviewer,
        "grade": grade,
        "ordinal_health": 7 if grade == "B" else 6,
        "category_ratings": {"complexity": 6},
        "confidence": 0.8,
        "insufficient_evidence": False,
        "status": "finalized",
    }


def _manifest() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "benchmark_version": "pilot-1",
        "scoring_version": "1.0",
        "cases": [{"metadata": _metadata(), "scan_file": "findings/csb-001.json"}],
    }


def test_manifest_requires_complete_strata_and_unique_cases() -> None:
    validate_pilot_manifest(_manifest())
    broken = _manifest()
    broken["cases"] = [*broken["cases"], broken["cases"][0]]  # type: ignore[index]
    with pytest.raises(EvidenceValidationError, match="unique"):
        validate_pilot_manifest(broken)


def test_packet_is_blinded_and_sampling_is_stratified_deterministic() -> None:
    scan = _scan()
    packet = make_review_packet(_metadata(), scan, reviewer_id="reviewer-01")
    assert packet["packet_version"] == REVIEW_PACKET_VERSION
    assert packet["blinding"] == {
        "score_hidden": True,
        "grade_hidden": True,
        "other_reviews_hidden": True,
    }
    assert len(packet["finding_reviews"]) == 3
    assert stratified_finding_sample(scan["findings"]) == stratified_finding_sample(
        list(reversed(scan["findings"]))
    )  # type: ignore[arg-type,index]


def test_adjudication_preserves_independent_disagreement() -> None:
    packet = make_adjudication_packet([_label("reviewer-01", "B"), _label("reviewer-02", "C")])
    assert packet["status"] == "draft"
    assert packet["disagreement"]["grades"] == ["B", "C"]
    assert len(packet["independent_opinions"]) == 2


def test_accuracy_refused_without_two_finalized_labels_and_adjudication() -> None:
    manifest = _manifest()
    manifest["cases"][0]["scan"] = _scan()  # type: ignore[index]
    with pytest.raises(EvidenceValidationError, match="two finalized independent"):
        load_finalized_independent_labels(manifest, [_label("reviewer-01", "B")])
    with pytest.raises(EvidenceValidationError, match="adjudication"):
        load_finalized_independent_labels(
            manifest, [_label("reviewer-01", "B"), _label("reviewer-02", "C")]
        )


def test_finalized_adjudication_enables_evaluator_case() -> None:
    labels = [_label("reviewer-01", "B"), _label("reviewer-02", "C")]
    adjudication = make_adjudication_packet(labels)
    adjudication.update(
        {
            "grade": "B",
            "ordinal_health": 7,
            "category_ratings": {"complexity": 6},
            "status": "finalized",
        }
    )
    adjudication["disagreement"]["resolution_rationale"] = "Evidence favored B."
    manifest = _manifest()
    manifest["cases"][0].update({"scan": _scan(), "adjudicated_label": adjudication})  # type: ignore[index,union-attr]
    cases = load_finalized_independent_labels(manifest, labels)
    assert cases[0]["actual_grade"] == "B"
    assert cases[0]["expert_grade"] == "B"
