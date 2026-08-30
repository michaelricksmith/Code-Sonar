"""In-memory model registry and champion selection metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ml.evaluation.metrics import BinaryClassificationMetrics
from app.ml.features import FEATURE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ModelRecord:
    task: str
    model_name: str
    model_version: str
    metrics: BinaryClassificationMetrics
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    is_champion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "is_champion": self.is_champion,
            "metrics": self.metrics.to_dict(),
        }


class ModelRegistry:
    """Small deterministic registry used before persistent artifact storage exists."""

    def __init__(self) -> None:
        self._records: list[ModelRecord] = []

    def register(self, record: ModelRecord) -> None:
        self._records = [
            existing
            for existing in self._records
            if not (
                existing.task == record.task
                and existing.model_name == record.model_name
                and existing.model_version == record.model_version
            )
        ]
        self._records.append(record)

    def records_for_task(self, task: str) -> tuple[ModelRecord, ...]:
        matches = (record for record in self._records if record.task == task)
        return tuple(sorted(matches, key=lambda record: record.model_name))

    def choose_champion(self, task: str) -> ModelRecord:
        candidates = list(self.records_for_task(task))
        if not candidates:
            raise ValueError(f"No models registered for task {task!r}")
        winner = max(
            candidates,
            key=lambda record: (
                record.metrics.f1,
                record.metrics.roc_auc or -1.0,
                record.model_name,
            ),
        )
        updated: list[ModelRecord] = []
        champion: ModelRecord | None = None
        for record in self._records:
            is_champion = record.task == task and record.model_name == winner.model_name
            replacement = ModelRecord(
                task=record.task,
                model_name=record.model_name,
                model_version=record.model_version,
                metrics=record.metrics,
                feature_schema_version=record.feature_schema_version,
                is_champion=is_champion,
            )
            updated.append(replacement)
            if is_champion:
                champion = replacement
        self._records = updated
        if champion is None:
            raise RuntimeError("Champion selection failed")
        return champion
