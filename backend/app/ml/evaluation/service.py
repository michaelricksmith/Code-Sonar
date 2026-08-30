"""Model-agnostic train/evaluate orchestration for Code Sonar classifiers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ml.datasets import DatasetRow
from app.ml.evaluation.metrics import BinaryClassificationMetrics, evaluate_binary_classification
from app.ml.features import ScanFeatureVector


class PredictionProtocol(Protocol):
    predicted_class: int
    probability: float


class BinaryModelProtocol(Protocol):
    model_name: str
    model_version: str

    def fit(self, rows: list[DatasetRow]) -> None: ...

    def predict(self, features: ScanFeatureVector) -> PredictionProtocol: ...


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    model_name: str
    model_version: str
    train_rows: int
    test_rows: int
    metrics: BinaryClassificationMetrics


def train_and_evaluate(
    model: BinaryModelProtocol,
    train_rows: list[DatasetRow],
    test_rows: list[DatasetRow],
) -> EvaluationRun:
    """Fit on train rows and evaluate only labeled test rows."""
    labeled_test = [row for row in test_rows if row.label is not None]
    if not labeled_test:
        raise ValueError("At least one labeled test row is required")

    model.fit(train_rows)
    y_true: list[int] = []
    y_pred: list[int] = []
    probabilities: list[float] = []
    for row in labeled_test:
        if row.label is None:
            continue
        prediction = model.predict(row.features)
        y_true.append(int(row.label.value))
        y_pred.append(prediction.predicted_class)
        probabilities.append(prediction.probability)

    return EvaluationRun(
        model_name=model.model_name,
        model_version=model.model_version,
        train_rows=len(train_rows),
        test_rows=len(labeled_test),
        metrics=evaluate_binary_classification(y_true, y_pred, probabilities),
    )
