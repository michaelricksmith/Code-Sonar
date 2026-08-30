"""Persistent metadata storage for evaluated Code Sonar ML models."""

from __future__ import annotations

import json
from pathlib import Path

from app.ml.evaluation.registry import ModelRecord, ModelRegistry

REGISTRY_SCHEMA_VERSION = "1.0"


class JsonModelRegistryStore:
    """Persist model metadata as deterministic JSON.

    This store intentionally persists metadata only. Serialized estimator binaries
    are handled separately so registry corruption cannot execute arbitrary code.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> ModelRegistry:
        if not self._path.exists():
            return ModelRegistry()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise ValueError("Unsupported ML registry schema version")
        raw_records = payload.get("records", [])
        if not isinstance(raw_records, list):
            raise ValueError("ML registry records must be a list")
        records = [ModelRecord.from_dict(record) for record in raw_records]
        return ModelRegistry(records)

    def save(self, registry: ModelRegistry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "records": [record.to_dict() for record in registry.all_records()],
        }
        serialized = json.dumps(payload, sort_keys=True, indent=2) + "\n"
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(self._path)
