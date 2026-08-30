"""ML-2 Logistic Regression and evaluation invariants."""

from app.ml.datasets import DatasetRow, LabelProvenance, LabelTrustTier
from app.ml.evaluation import evaluate_binary_classification, grouped_train_test_split
from app.ml.features import ScanFeatureVector
from app.ml.models import LogisticDebtRiskModel


def _features(signal: float) -> ScanFeatureVector:
    return ScanFeatureVector(
        score=850.0 - signal * 100.0,
        total_debt_points=signal * 20.0,
        finding_count=signal * 5.0,
        severity_info=0.0,
        severity_warning=signal,
        severity_error=signal,
        severity_critical=signal,
        category_complexity=signal,
        category_staleness=0.0,
        category_security=signal,
        category_duplication=0.0,
        category_testing=signal,
        category_maintainability=signal,
        source_findings=signal * 3.0,
        test_findings=0.0,
        fixture_findings=0.0,
        mean_confidence=0.9,
        mean_debt_points=signal * 4.0,
        max_finding_risk=signal * 10.0,
        analyzer_diversity=max(1.0, signal * 2.0),
    )


def _row(index: int, group: str, signal: float, label: int) -> DatasetRow:
    return DatasetRow(
        row_id=f"row-{index}",
        repository_group=group,
        lineage_id=f"lineage-{group}",
        scan_id=f"scan-{index}",
        features=_features(signal),
        label=LabelProvenance(
            task="debt_risk",
            value=str(label),
            trust_tier=LabelTrustTier.PROXY,
            source="unit-test",
        ),
    )


def test_grouped_split_keeps_repositories_disjoint() -> None:
    rows = [
        _row(1, "repo-a", 0.1, 0),
        _row(2, "repo-a", 0.2, 0),
        _row(3, "repo-b", 0.8, 1),
        _row(4, "repo-b", 0.9, 1),
        _row(5, "repo-c", 0.3, 0),
        _row(6, "repo-c", 0.7, 1),
        _row(7, "repo-d", 0.4, 0),
        _row(8, "repo-d", 0.6, 1),
    ]
    split = grouped_train_test_split(rows, test_size=0.25, random_state=42)

    assert split.train_groups
    assert split.test_groups
    assert split.train_groups.isdisjoint(split.test_groups)


def test_logistic_model_returns_probability_and_explanation() -> None:
    rows = [
        _row(1, "repo-a", 0.1, 0),
        _row(2, "repo-b", 0.2, 0),
        _row(3, "repo-c", 0.8, 1),
        _row(4, "repo-d", 0.9, 1),
    ]
    model = LogisticDebtRiskModel()
    model.fit(rows)

    prediction = model.predict(_features(0.85))

    assert 0.0 <= prediction.probability <= 1.0
    assert 0.5 <= prediction.confidence <= 1.0
    assert prediction.predicted_class in {0, 1}
    assert len(prediction.feature_contributions) == len(ScanFeatureVector.feature_names())
    assert prediction.model_name == "logistic_debt_risk"
    assert prediction.feature_schema_version == "1.0"


def test_logistic_model_is_reproducible() -> None:
    rows = [
        _row(1, "repo-a", 0.1, 0),
        _row(2, "repo-b", 0.2, 0),
        _row(3, "repo-c", 0.8, 1),
        _row(4, "repo-d", 0.9, 1),
    ]
    first = LogisticDebtRiskModel()
    second = LogisticDebtRiskModel()
    first.fit(rows)
    second.fit(rows)

    assert first.predict(_features(0.75)).to_dict() == second.predict(_features(0.75)).to_dict()


def test_binary_metrics_include_confusion_matrix_and_auc() -> None:
    metrics = evaluate_binary_classification(
        [0, 0, 1, 1],
        [0, 1, 1, 1],
        [0.1, 0.6, 0.7, 0.9],
    )

    assert metrics.true_negative == 1
    assert metrics.false_positive == 1
    assert metrics.false_negative == 0
    assert metrics.true_positive == 2
    assert metrics.roc_auc is not None
