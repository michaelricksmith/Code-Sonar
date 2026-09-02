from __future__ import annotations

import pytest

from app.calibration.capture import capture_frozen_scan
from app.calibration.contracts import CONTRACT_VERSION
from app.calibration.metrics import bootstrap_ci, evaluate, spearman, weighted_kappa
from app.calibration.validation import (
    EvidenceValidationError,
    artifact_sha256,
    validate_artifact,
    verify_artifact_hash,
)


def _scan(status: str = "completed") -> dict[str, object]:
    return {
        "repository": "/private/customer/repo",
        "scoring_version": "1.0",
        "analyzer_execution": [{"analyzer": "secrets", "status": status, "finding_count": 1}],
        "score": 700,
        "grade": "B",
        "category_scores": {"security": 700},
        "total_debt_points": 10,
        "findings": [
            {
                "id": "f1",
                "rule_id": "secrets:key",
                "category": "security",
                "severity": "error",
                "confidence": 0.95,
                "debt_points": 10,
                "analyzer": "secrets",
                "file_path": "src/private.py",
                "evidence": "customer-secret",
                "message": "private message",
            }
        ],
    }


def test_capture_excludes_identity_paths_and_source_evidence() -> None:
    captured = capture_frozen_scan(
        _scan(),
        case_id="csb-001",
        analyzer_versions={"secrets": "1"},
        expected_scoring_version="1.0",
    )
    encoded = str(captured)
    assert "customer" not in encoded
    assert "file_path" not in encoded
    assert "evidence" not in captured["findings"][0]
    assert len(captured["artifact_sha256"]) == 64


def test_capture_rejects_incomplete_scan() -> None:
    with pytest.raises(EvidenceValidationError, match="incomplete"):
        capture_frozen_scan(
            _scan("failed"),
            case_id="csb-001",
            analyzer_versions={"secrets": "1"},
            expected_scoring_version="1.0",
        )


def test_capture_rejects_scoring_version_mismatch() -> None:
    with pytest.raises(EvidenceValidationError, match="mismatch"):
        capture_frozen_scan(
            _scan(),
            case_id="csb-001",
            analyzer_versions={"secrets": "1"},
            expected_scoring_version="2.0",
        )


def test_validation_rejects_version_mismatch_and_forbidden_nested_key() -> None:
    artifact = capture_frozen_scan(
        _scan(),
        case_id="csb-001",
        analyzer_versions={"secrets": "1"},
        expected_scoring_version="1.0",
    )
    with pytest.raises(EvidenceValidationError, match="mismatch"):
        validate_artifact(artifact, expected_scoring_version="2.0")
    artifact["extra"] = {"repository_path": "C:/private"}
    with pytest.raises(EvidenceValidationError, match="forbidden"):
        validate_artifact(artifact)


def test_hash_is_canonical() -> None:
    assert artifact_sha256({"a": 1, "b": 2}) == artifact_sha256({"b": 2, "a": 1})


def test_loaded_artifact_hash_is_verified() -> None:
    artifact = capture_frozen_scan(
        _scan(),
        case_id="csb-001",
        analyzer_versions={"secrets": "1"},
        expected_scoring_version="1.0",
    )
    verify_artifact_hash(artifact)
    artifact["score"] = 701
    with pytest.raises(EvidenceValidationError, match="mismatch"):
        verify_artifact_hash(artifact)


def test_label_contract_accepts_complete_blinded_label() -> None:
    validate_artifact(
        {
            "contract_version": CONTRACT_VERSION,
            "artifact_type": "expert_label",
            "case_id": "csb-001",
            "reviewer_id": "reviewer-01",
            "grade": "B",
            "ordinal_health": 7,
            "category_ratings": {"security": 8},
            "confidence": 0.8,
        }
    )


def test_ordinal_metrics() -> None:
    assert weighted_kappa([0, 1, 2], [0, 1, 2], levels=3) == 1
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1)


def test_evaluator_reports_precision_severity_strata_and_deterministic_ci() -> None:
    cases = [
        {
            "actual_grade": "A",
            "expert_grade": "A",
            "expert_ordinal_health": 9,
            "strata": {"size": "small"},
        },
        {
            "actual_grade": "C",
            "expert_grade": "B",
            "expert_ordinal_health": 7,
            "strata": {"size": "large"},
        },
        {
            "actual_grade": "F",
            "expert_grade": "F",
            "expert_ordinal_health": 2,
            "strata": {"size": "large"},
        },
    ]
    reviews = [
        {
            "analyzer": "secrets",
            "verdict": "true_positive",
            "reported_severity": "error",
            "expert_severity": "error",
        },
        {
            "analyzer": "secrets",
            "verdict": "false_positive",
            "reported_severity": "error",
            "expert_severity": "warning",
        },
    ]
    first, second = evaluate(cases, reviews), evaluate(cases, reviews)
    assert first == second
    assert first["per_analyzer_precision"]["secrets"]["precision"] == 0.5
    assert first["severity_agreement"]["exact"] == 0.5
    assert first["strata"]["size=large"]["case_count"] == 2


def test_bootstrap_empty_is_none() -> None:
    assert bootstrap_ci([], lambda _: 1.0) is None
