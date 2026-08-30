"""Process-wide ML registry state for read-only API access.

The runtime registry is intentionally metadata-only. Model estimator loading
and prediction execution are introduced separately so read endpoints cannot
trigger training or executable artifact deserialization.
"""

from __future__ import annotations

from app.ml.evaluation import ModelRegistry

_model_registry = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    """Return the process-wide evaluated-model metadata registry."""
    return _model_registry


def set_model_registry(registry: ModelRegistry) -> None:
    """Replace the process-wide registry; primarily used by tests/startup wiring."""
    global _model_registry
    _model_registry = registry
