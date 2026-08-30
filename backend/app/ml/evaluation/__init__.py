"""Evaluation utilities for Code Sonar ML models."""

from app.ml.evaluation.metrics import BinaryClassificationMetrics, evaluate_binary_classification
from app.ml.evaluation.persistence import JsonModelRegistryStore
from app.ml.evaluation.registry import ModelRecord, ModelRegistry
from app.ml.evaluation.service import EvaluationRun, train_and_evaluate
from app.ml.evaluation.split import GroupedSplit, grouped_train_test_split

__all__ = [
    "BinaryClassificationMetrics",
    "EvaluationRun",
    "GroupedSplit",
    "JsonModelRegistryStore",
    "ModelRecord",
    "ModelRegistry",
    "evaluate_binary_classification",
    "grouped_train_test_split",
    "train_and_evaluate",
]
