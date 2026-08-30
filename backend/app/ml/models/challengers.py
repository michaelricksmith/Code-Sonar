"""Decision Tree, SVM, and KNN challenger models for debt-risk classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from app.ml.datasets import DatasetRow
from app.ml.features import FEATURE_SCHEMA_VERSION, ScanFeatureVector


@dataclass(frozen=True, slots=True)
class ChallengerPrediction:
    predicted_class: int
    probability: float
    confidence: float
    model_name: str
    model_version: str = "0.1.0"
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    explanation: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_class": self.predicted_class,
            "probability": self.probability,
            "confidence": self.confidence,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "explanation": list(self.explanation),
        }


def _training_data(rows: list[DatasetRow]) -> tuple[list[list[float]], list[int]]:
    labeled = [row for row in rows if row.label is not None]
    if len(labeled) < 2:
        raise ValueError("At least two labeled rows are required")
    labels = [int(row.label.value) for row in labeled if row.label is not None]
    if len(set(labels)) < 2:
        raise ValueError("Classifier requires at least two label classes")
    features = [list(row.features.ordered_values()) for row in labeled]
    return features, labels


class DecisionTreeDebtRiskModel:
    """Interpretable tree challenger with a reproducible random state."""

    model_name = "decision_tree_debt_risk"
    model_version = "0.1.0"

    def __init__(self) -> None:
        self._classifier = DecisionTreeClassifier(max_depth=5, random_state=42)
        self._is_fitted = False

    def fit(self, rows: list[DatasetRow]) -> None:
        x_train, y_train = _training_data(rows)
        self._classifier.fit(x_train, y_train)
        self._is_fitted = True

    def predict(self, features: ScanFeatureVector) -> ChallengerPrediction:
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")
        vector = [list(features.ordered_values())]
        probability = float(self._classifier.predict_proba(vector)[0][1])
        predicted_class = int(probability >= 0.5)
        confidence = probability if predicted_class else 1.0 - probability
        path = self._classifier.decision_path(vector)
        explanation = tuple(f"tree_node:{int(node)}" for node in path.indices)
        return ChallengerPrediction(
            predicted_class=predicted_class,
            probability=probability,
            confidence=confidence,
            model_name=self.model_name,
            explanation=explanation,
        )


class SVMDebtRiskModel:
    """Scaled probabilistic SVM challenger for nonlinear boundaries."""

    model_name = "svm_debt_risk"
    model_version = "0.1.0"

    def __init__(self) -> None:
        self._pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("classifier", SVC(kernel="rbf", probability=True, random_state=42)),
            ]
        )
        self._is_fitted = False

    def fit(self, rows: list[DatasetRow]) -> None:
        x_train, y_train = _training_data(rows)
        self._pipeline.fit(x_train, y_train)
        self._is_fitted = True

    def predict(self, features: ScanFeatureVector) -> ChallengerPrediction:
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")
        vector = [list(features.ordered_values())]
        probability = float(self._pipeline.predict_proba(vector)[0][1])
        predicted_class = int(probability >= 0.5)
        confidence = probability if predicted_class else 1.0 - probability
        return ChallengerPrediction(
            predicted_class=predicted_class,
            probability=probability,
            confidence=confidence,
            model_name=self.model_name,
        )


class KNNDebtRiskModel:
    """Similarity-oriented KNN challenger for historical-case reasoning."""

    model_name = "knn_debt_risk"
    model_version = "0.1.0"

    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None

    def fit(self, rows: list[DatasetRow]) -> None:
        x_train, y_train = _training_data(rows)
        neighbors = min(5, len(x_train))
        self._pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("classifier", KNeighborsClassifier(n_neighbors=neighbors, weights="distance")),
            ]
        )
        self._pipeline.fit(x_train, y_train)

    def predict(self, features: ScanFeatureVector) -> ChallengerPrediction:
        if self._pipeline is None:
            raise RuntimeError("Model must be fitted before prediction")
        vector = [list(features.ordered_values())]
        probability = float(self._pipeline.predict_proba(vector)[0][1])
        predicted_class = int(probability >= 0.5)
        confidence = probability if predicted_class else 1.0 - probability
        return ChallengerPrediction(
            predicted_class=predicted_class,
            probability=probability,
            confidence=confidence,
            model_name=self.model_name,
        )
