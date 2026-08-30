"""Model registry metadata and deterministic champion selection."""

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
    dataset_version: str | None = None
    trained_at: str | None = None
    artifact_ref: str | None = None
    is_champion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "dataset_version": self.dataset_version,
            "trained_at": self.trained_at,
            "artifact_ref": self.artifact_ref,
            "is_champion": self.is_champion,
            "metrics": self.metrics.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ModelRecord:
        metrics_payload = payload["metrics"]
        confusion = metrics_payload["confusion_matrix"]
        metrics = BinaryClassificationMetrics(
            accuracy=float(metrics_payload["accuracy"]),
            precision=float(metrics_payload["precision"]),
            recall=float(metrics_payload["recall"]),
            f1=float(metrics_payload["f1"]),
            roc_auc=(
                None
                if metrics_payload.get("roc_auc") is None
                else float(metrics_payload["roc_auc"])
            ),
            true_negative=int(confusion["tn"]),
            false_positive=int(confusion["fp"]),
            false_negative=int(confusion["fn"]),
            true_positive=int(confusion["tp"]),
        )
        return cls(
            task=str(payload["task"]),
            model_name=str(payload["model_name"]),
            model_version=str(payload["model_version"]),
            feature_schema_version=str(
                payload.get("feature_schema_version", FEATURE_SCHEMA_VERSION)
            ),
            dataset_version=(
                None
                if payload.get("dataset_version") is None
                else str(payload["dataset_version"])
            ),
            trained_at=(
                None if payload.get("trained_at") is None else str(payload["trained_at"])
            ),
            artifact_ref=(
                None if payload.get("artifact_ref") is None else str(payload["artifact_ref"])
            ),
            is_champion=bool(payload.get("is_champion", False)),
            metrics=metrics,
        )


class ModelRegistry:
    """Deterministic registry of evaluated model metadata."""

    def __init__(self, records: list[ModelRecord] | None = None) -> None:
        self._records: list[ModelRecord] = list(records or [])

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

    def all_records(self) -> tuple[ModelRecord, ...]:
        return tuple(
            sorted(
                self._records,
                key=lambda record: (record.task, record.model_name, record.model_version),
            )
        )

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
                dataset_version=record.dataset_version,
                trained_at=record.trained_at,
                artifact_ref=record.artifact_ref,
                is_champion=is_champion,
            )
            updated.append(replacement)
            if is_champion:
                champion = replacement
        self._records = updated
        if champion is None:
            raise RuntimeError("Champion selection failed")
        return champion
