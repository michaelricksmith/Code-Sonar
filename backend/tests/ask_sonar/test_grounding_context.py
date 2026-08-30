"""Ask Sonar grounding invariants."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.ask_sonar.context import build_grounding_context
from app.history import FindingSnapshot, ScanRecord
from app.ml.datasets import DatasetRow, LabelProvenance, LabelTrustTier
from app.ml.features import ScanFeatureVector
from app.ml.runtime import (
    clear_prediction_models,
    clear_similarity_indexes,
    register_prediction_model,
    register_similarity_index,
)
from app.ml.similarity import SimilarityIndex


@pytest.fixture(autouse=True)
def reset_ml_runtime():
    clear_prediction_models()
    clear_similarity_indexes()
    yield
    clear_prediction_models()
    clear_similarity_indexes()


def _finding(
    finding_id: str,
    *,
    severity: str,
    debt_points: int,
    file_path: str,
) -> FindingSnapshot:
    return FindingSnapshot.from_dict(
        {
            "id": finding_id,
            "rule_id": "rule-1",
            "category": "maintainability",
            "severity": severity,
            "confidence": 0.9,
            "file_path": file_path,
            "line_start": 10,
            "line_end": 12,
            "symbol": "target",
            "evidence": "redacted evidence",
            "message": f"message {finding_id}",
            "suggestion": "refactor",
            "debt_points": debt_points,
            "analyzer": "test-analyzer",
            "metadata": {},
        }
    )


def _record(scan_id: str = "scan-current") -> ScanRecord:
    findings = [
        _finding("low", severity="warning", debt_points=2, file_path="b.py"),
        _finding("high", severity="critical", debt_points=8, file_path="a.py"),
    ]
    return ScanRecord(
        scan_id=scan_id,
        repository_id="repo-1",
        repository_path="example/repo",
        scanned_at="2026-08-30T20:00:00+00:00",
        schema_version="1.0",
        score=640,
        grade="C",
        total_debt_points=10,
        finding_count=2,
        category_scores={"maintainability": 620},
        severity_distribution={"warning": 1, "critical": 1},
        findings_by_category={"maintainability": 2},
        findings_source_breakdown={"source": 2, "test": 0, "fixture": 0},
        findings=findings,
    )


@dataclass(frozen=True)
class FakePrediction:
    model_name: str = "fake-risk"
    model_version: str = "test-1"

    def to_dict(self) -> dict[str, object]:
        return {
            "predicted_class": 1,
            "probability": 0.81,
            "confidence": 0.81,
            "model_name": self.model_name,
            "model_version": self.model_version,
        }


class FakeModel:
    model_name = "fake-risk"
    model_version = "test-1"

    def predict(self, features: ScanFeatureVector) -> FakePrediction:
        assert features.score == 640.0
        return FakePrediction()


def _row(scan_id: str, signal: float) -> DatasetRow:
    features = ScanFeatureVector(
        score=640.0 + signal,
        total_debt_points=10.0 + signal,
        finding_count=2.0,
        severity_info=0.0,
        severity_warning=1.0,
        severity_error=0.0,
        severity_critical=1.0,
        category_complexity=0.0,
        category_staleness=0.0,
        category_security=0.0,
        category_duplication=0.0,
        category_testing=0.0,
        category_maintainability=2.0,
        source_findings=2.0,
        test_findings=0.0,
        fixture_findings=0.0,
        mean_confidence=0.9,
        mean_debt_points=5.0,
        max_finding_risk=32.0,
        analyzer_diversity=1.0,
    )
    return DatasetRow(
        row_id=f"row-{scan_id}",
        repository_group=f"repo-{scan_id}",
        lineage_id=f"lineage-{scan_id}",
        scan_id=scan_id,
        features=features,
        label=LabelProvenance(
            task="debt_risk",
            value="1",
            trust_tier=LabelTrustTier.REMEDIATION_OUTCOME,
            source="unit-test",
        ),
    )


def test_grounding_keeps_deterministic_authority_when_ml_unavailable() -> None:
    context = build_grounding_context(_record(), top_findings_limit=1)

    assert context["source_policy"]["deterministic_is_authoritative"] is True
    assert context["source_policy"]["ml_is_advisory"] is True
    assert context["deterministic_score_unchanged"] is True
    assert context["deterministic"]["score"] == 640
    assert context["deterministic"]["grade"] == "C"
    assert context["deterministic"]["top_findings"][0]["id"] == "high"
    assert context["ml_prediction"]["status"] == "unavailable"
    assert context["historical_similarity"]["status"] == "unavailable"


def test_grounding_attaches_advisory_prediction_and_similarity() -> None:
    register_prediction_model("debt_risk", FakeModel())
    index = SimilarityIndex()
    index.fit([_row("scan-current", 0.0), _row("scan-near", 1.0), _row("scan-far", 20.0)])
    register_similarity_index("debt_risk", index)

    context = build_grounding_context(_record(), similar_limit=2)

    assert context["ml_prediction"]["status"] == "available"
    assert context["ml_prediction"]["advisory_only"] is True
    assert context["ml_prediction"]["result"]["probability"] == 0.81
    assert context["historical_similarity"]["status"] == "available"
    cases = context["historical_similarity"]["cases"]
    assert cases[0]["scan_id"] == "scan-near"
    assert all(case["scan_id"] != "scan-current" for case in cases)
    assert cases[0]["label_trust_tier"] == "remediation_outcome"
