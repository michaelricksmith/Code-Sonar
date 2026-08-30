"""ML-4 persistent registry metadata tests."""

import json
from pathlib import Path

import pytest

from app.ml.evaluation import (
    BinaryClassificationMetrics,
    JsonModelRegistryStore,
    ModelRecord,
    ModelRegistry,
)


def _metrics(f1: float = 0.8) -> BinaryClassificationMetrics:
    return BinaryClassificationMetrics(
        accuracy=0.8,
        precision=0.8,
        recall=0.8,
        f1=f1,
        roc_auc=0.85,
        true_negative=4,
        false_positive=1,
        false_negative=1,
        true_positive=4,
    )


def test_registry_metadata_round_trip(tmp_path: Path) -> None:
    registry = ModelRegistry()
    registry.register(
        ModelRecord(
            task="debt_risk",
            model_name="logistic_debt_risk",
            model_version="0.1.0",
            metrics=_metrics(),
            dataset_version="dataset-2026-08-30",
            trained_at="2026-08-30T19:00:00+00:00",
            artifact_ref="models/logistic_debt_risk/0.1.0",
            is_champion=True,
        )
    )

    path = tmp_path / "ml-registry.json"
    store = JsonModelRegistryStore(path)
    store.save(registry)
    loaded = store.load()

    assert loaded.all_records() == registry.all_records()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["records"][0]["dataset_version"] == "dataset-2026-08-30"


def test_registry_store_returns_empty_registry_when_missing(tmp_path: Path) -> None:
    store = JsonModelRegistryStore(tmp_path / "missing.json")
    assert store.load().all_records() == ()


def test_registry_store_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "ml-registry.json"
    path.write_text('{"schema_version":"999","records":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported ML registry schema version"):
        JsonModelRegistryStore(path).load()


def test_champion_selection_preserves_lifecycle_metadata() -> None:
    registry = ModelRegistry(
        [
            ModelRecord(
                task="debt_risk",
                model_name="logistic_debt_risk",
                model_version="0.1.0",
                metrics=_metrics(0.7),
                dataset_version="dataset-a",
                trained_at="2026-08-30T19:00:00+00:00",
                artifact_ref="artifact-a",
            ),
            ModelRecord(
                task="debt_risk",
                model_name="svm_debt_risk",
                model_version="0.1.0",
                metrics=_metrics(0.9),
                dataset_version="dataset-b",
                trained_at="2026-08-30T20:00:00+00:00",
                artifact_ref="artifact-b",
            ),
        ]
    )

    champion = registry.choose_champion("debt_risk")

    assert champion.model_name == "svm_debt_risk"
    assert champion.dataset_version == "dataset-b"
    assert champion.trained_at == "2026-08-30T20:00:00+00:00"
    assert champion.artifact_ref == "artifact-b"
