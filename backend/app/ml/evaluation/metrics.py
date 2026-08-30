"""Stable evaluation metrics for binary Code Sonar ML tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass(frozen=True, slots=True)
class BinaryClassificationMetrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float | None
    true_negative: int
    false_positive: int
    false_negative: int
    true_positive: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "roc_auc": self.roc_auc,
            "confusion_matrix": {
                "tn": self.true_negative,
                "fp": self.false_positive,
                "fn": self.false_negative,
                "tp": self.true_positive,
            },
        }


def evaluate_binary_classification(
    y_true: list[int],
    y_pred: list[int],
    y_probability: list[float] | None = None,
) -> BinaryClassificationMetrics:
    """Evaluate a binary classifier using a stable metric bundle."""
    if not y_true or len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must be non-empty and equal length")
    if y_probability is not None and len(y_probability) != len(y_true):
        raise ValueError("y_probability must match y_true length")

    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())

    roc_auc: float | None = None
    if y_probability is not None and len(set(y_true)) == 2:
        roc_auc = float(roc_auc_score(y_true, y_probability))

    return BinaryClassificationMetrics(
        accuracy=float(accuracy_score(y_true, y_pred)),
        precision=float(precision_score(y_true, y_pred, zero_division=0)),
        recall=float(recall_score(y_true, y_pred, zero_division=0)),
        f1=float(f1_score(y_true, y_pred, zero_division=0)),
        roc_auc=roc_auc,
        true_negative=tn,
        false_positive=fp,
        false_negative=fn,
        true_positive=tp,
    )
