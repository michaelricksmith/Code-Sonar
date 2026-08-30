"""ML-3 challenger-model and registry invariants."""

from app.ml.datasets import DatasetRow, LabelProvenance, LabelTrustTier
from app.ml.evaluation import BinaryClassificationMetrics, ModelRecord, ModelRegistry
from app.ml.features import ScanFeatureVector
from app.ml.models import DecisionTreeDebtRiskModel, KNNDebtRiskModel, SVMDebtRiskModel


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


def _row(index: int, signal: float, label: int) -> DatasetRow:
    return DatasetRow(
        row_id=f"row-{index}",
        repository_group=f"repo-{index}",
        lineage_id=f"repo-{index}",
        scan_id=f"scan-{index}",
        features=_features(signal),
        label=LabelProvenance(
            task="debt_risk",
            value=str(label),
            trust_tier=LabelTrustTier.PROXY,
            source="unit-test",
        ),
    )


def _rows() -> list[DatasetRow]:
    return [
        _row(1, 0.1, 0),
        _row(2, 0.2, 0),
        _row(3, 0.3, 0),
        _row(4, 0.7, 1),
        _row(5, 0.8, 1),
        _row(6, 0.9, 1),
    ]


def test_all_challengers_return_versioned_probabilities() -> None:
    for model in (DecisionTreeDebtRiskModel(), SVMDebtRiskModel(), KNNDebtRiskModel()):
        model.fit(_rows())
        prediction = model.predict(_features(0.85))
        assert prediction.predicted_class in {0, 1}
        assert 0.0 <= prediction.probability <= 1.0
        assert 0.5 <= prediction.confidence <= 1.0
        assert prediction.feature_schema_version == "1.0"


def _metrics(f1: float, auc: float) -> BinaryClassificationMetrics:
    return BinaryClassificationMetrics(
        accuracy=f1,
        precision=f1,
        recall=f1,
        f1=f1,
        roc_auc=auc,
        true_negative=1,
        false_positive=0,
        false_negative=0,
        true_positive=1,
    )


def test_registry_selects_task_champion_by_f1_then_auc() -> None:
    registry = ModelRegistry()
    registry.register(ModelRecord("debt_risk", "logistic", "0.1.0", _metrics(0.80, 0.90)))
    registry.register(ModelRecord("debt_risk", "tree", "0.1.0", _metrics(0.85, 0.86)))
    registry.register(ModelRecord("debt_risk", "svm", "0.1.0", _metrics(0.85, 0.92)))

    champion = registry.choose_champion("debt_risk")

    assert champion.model_name == "svm"
    assert champion.is_champion is True
    assert sum(record.is_champion for record in registry.records_for_task("debt_risk")) == 1
