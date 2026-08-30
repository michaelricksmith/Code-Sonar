"""Explainable Logistic Regression baseline for debt-risk classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.datasets import DatasetRow
from app.ml.features import FEATURE_SCHEMA_VERSION, ScanFeatureVector

MODEL_NAME = "logistic_debt_risk"
MODEL_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class LogisticPrediction:
    predicted_class: int
    probability: float
    confidence: float
    feature_contributions: tuple[tuple[str, float], ...]
    model_name: str = MODEL_NAME
    model_version: str = MODEL_VERSION
    feature_schema_version: str = FEATURE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_class": self.predicted_class,
            "probability": self.probability,
            "confidence": self.confidence,
            "feature_contributions": [
                {"feature": name, "contribution": value}
                for name, value in self.feature_contributions
            ],
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
        }


class LogisticDebtRiskModel:
    """Versioned, reproducible Logistic Regression baseline."""

    model_name = MODEL_NAME
    model_version = MODEL_VERSION

    def __init__(self) -> None:
        self._pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        random_state=42,
                        max_iter=1000,
                        solver="liblinear",
                    ),
                ),
            ]
        )
        self._is_fitted = False

    def fit(self, rows: list[DatasetRow]) -> None:
        """Fit using labeled rows from the current feature schema."""
        labeled = [row for row in rows if row.label is not None]
        if len(labeled) < 2:
            raise ValueError("At least two labeled rows are required")
        for row in labeled:
            if row.feature_schema_version != FEATURE_SCHEMA_VERSION:
                raise ValueError("Incompatible feature schema version")

        labels: list[int] = []
        for row in labeled:
            assert row.label is not None
            if row.label.value not in {"0", "1"}:
                raise ValueError("Binary Logistic Regression labels must be '0' or '1'")
            labels.append(int(row.label.value))
        if len(set(labels)) < 2:
            raise ValueError("Logistic Regression requires at least two label classes")

        x_train = [list(row.features.ordered_values()) for row in labeled]
        self._pipeline.fit(x_train, labels)
        self._is_fitted = True

    def predict(self, features: ScanFeatureVector) -> LogisticPrediction:
        """Return probability plus linear feature contributions."""
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")

        vector = [list(features.ordered_values())]
        probability = float(self._pipeline.predict_proba(vector)[0][1])
        predicted_class = int(probability >= 0.5)
        confidence = probability if predicted_class == 1 else 1.0 - probability

        scaler = self._pipeline.named_steps["scaler"]
        classifier = self._pipeline.named_steps["classifier"]
        scaled = scaler.transform(vector)[0]
        coefficients = classifier.coef_[0]
        contributions = tuple(
            sorted(
                (
                    (name, float(value * coefficient))
                    for name, value, coefficient in zip(
                        ScanFeatureVector.feature_names(),
                        scaled,
                        coefficients,
                        strict=True,
                    )
                ),
                key=lambda item: (-abs(item[1]), item[0]),
            )
        )

        return LogisticPrediction(
            predicted_class=predicted_class,
            probability=probability,
            confidence=confidence,
            feature_contributions=contributions,
        )
