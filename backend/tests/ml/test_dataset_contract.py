"""ML-1 dataset contract invariants."""

from app.history import ScanRecord
from app.ml.datasets import LabelProvenance, LabelTrustTier, build_scan_dataset_row


def _empty_record() -> ScanRecord:
    return ScanRecord(
        scan_id="scan-1",
        repository_id="repo-1",
        repository_path="repo",
        scanned_at="2026-08-30T12:00:00+00:00",
        schema_version="1.0",
        score=850,
        grade="A",
        total_debt_points=0,
        finding_count=0,
        category_scores={},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={},
        findings=[],
    )


def test_dataset_row_is_stable_for_same_scan() -> None:
    first = build_scan_dataset_row(_empty_record()).to_dict()
    second = build_scan_dataset_row(_empty_record()).to_dict()

    assert first == second
    assert first["repository_group"] == "repo-1"
    assert first["lineage_id"] == "repo-1"
    assert first["scan_id"] == "scan-1"
    assert first["dataset_schema_version"] == "1.0"
    assert first["feature_schema_version"] == "1.0"


def test_proxy_label_is_explicitly_marked_proxy() -> None:
    label = LabelProvenance(
        task="debt_risk",
        value="high",
        trust_tier=LabelTrustTier.PROXY,
        source="deterministic-score-bootstrap",
    )

    payload = build_scan_dataset_row(_empty_record(), label=label).to_dict()

    assert payload["label"] == {
        "task": "debt_risk",
        "value": "high",
        "trust_tier": "proxy",
        "source": "deterministic-score-bootstrap",
        "observed_at": None,
        "is_proxy": True,
    }


def test_observed_outcome_is_not_marked_proxy() -> None:
    label = LabelProvenance(
        task="remediation_success",
        value="success",
        trust_tier=LabelTrustTier.REMEDIATION_OUTCOME,
        source="post-remediation-rescan",
        observed_at="2026-08-30T13:00:00+00:00",
    )

    payload = build_scan_dataset_row(_empty_record(), label=label).to_dict()

    assert payload["label"] is not None
    assert payload["label"]["is_proxy"] is False
    assert payload["label"]["trust_tier"] == "remediation_outcome"
