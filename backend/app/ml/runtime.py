"""Process-wide ML metadata, prediction, and similarity runtime state.

Read-only metadata access remains separate from prediction execution. Loaded
estimators and similarity indexes must be registered explicitly; requests never
train models or load artifacts implicitly.
"""

from __future__ import annotations

from typing import Callable, Protocol

from app.history import JsonlHistoryStore
from app.ml.evaluation import ModelRegistry
from app.ml.features import ScanFeatureVector, extract_scan_features
from app.ml.similarity import SimilarityIndex


class PredictionResultProtocol(Protocol):
    """Minimum prediction payload contract required by the HTTP surface."""

    model_name: str
    model_version: str

    def to_dict(self) -> dict[str, object]: ...


class PredictionModelProtocol(Protocol):
    """A fitted model that can predict from the current feature schema."""

    model_name: str
    model_version: str

    def predict(self, features: ScanFeatureVector) -> PredictionResultProtocol: ...


FeatureProvider = Callable[[str], ScanFeatureVector | None]

_model_registry = ModelRegistry()
_prediction_models: dict[str, PredictionModelProtocol] = {}
_similarity_indexes: dict[str, SimilarityIndex] = {}
_feature_provider: FeatureProvider | None = None


def get_model_registry() -> ModelRegistry:
    """Return the process-wide evaluated-model metadata registry."""
    return _model_registry


def set_model_registry(registry: ModelRegistry) -> None:
    """Replace the process-wide registry; primarily used by tests/startup wiring."""
    global _model_registry
    _model_registry = registry


def register_prediction_model(task: str, model: PredictionModelProtocol) -> None:
    """Register one already-fitted model for a prediction task."""
    if not task.strip():
        raise ValueError("Prediction task must be non-empty")
    _prediction_models[task] = model


def clear_prediction_models() -> None:
    """Clear loaded prediction models; primarily used by tests."""
    _prediction_models.clear()


def get_prediction_model(task: str) -> PredictionModelProtocol | None:
    """Return the explicitly loaded model for ``task``, if any."""
    return _prediction_models.get(task)


def register_similarity_index(task: str, index: SimilarityIndex) -> None:
    """Register one already-fitted historical similarity index for a task."""
    if not task.strip():
        raise ValueError("Similarity task must be non-empty")
    _similarity_indexes[task] = index


def clear_similarity_indexes() -> None:
    """Clear loaded similarity indexes; primarily used by tests."""
    _similarity_indexes.clear()


def get_similarity_index(task: str) -> SimilarityIndex | None:
    """Return the explicitly loaded similarity index for ``task``, if any."""
    return _similarity_indexes.get(task)


def set_feature_provider(provider: FeatureProvider | None) -> None:
    """Override stored-scan feature lookup; primarily used by tests."""
    global _feature_provider
    _feature_provider = provider


def _persisted_scan_features(scan_id: str) -> ScanFeatureVector | None:
    """Build the current feature vector from a persisted redacted scan record."""
    record = JsonlHistoryStore().get(scan_id)
    if record is None:
        return None
    return extract_scan_features(record)


def get_features_for_scan(scan_id: str) -> ScanFeatureVector | None:
    """Resolve features for a stored scan without triggering a new scan."""
    provider = _feature_provider or _persisted_scan_features
    return provider(scan_id)
