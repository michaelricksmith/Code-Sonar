"""Read-only HTTP surface for Code Sonar ML model metadata."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.ml.runtime import get_model_registry

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.get("/models")
async def list_models(
    task: str | None = Query(default=None, description="Optional prediction task filter"),
) -> dict[str, Any]:
    """Return registered model metadata without loading estimator artifacts."""
    registry = get_model_registry()
    records = registry.all_records() if task is None else registry.records_for_task(task)
    return {
        "count": len(records),
        "task": task,
        "models": [record.to_dict() for record in records],
    }


@router.get("/model-performance")
async def model_performance(
    task: str | None = Query(default=None, description="Optional prediction task filter"),
) -> dict[str, Any]:
    """Return evaluation metrics and champion state for registered models."""
    registry = get_model_registry()
    records = registry.all_records() if task is None else registry.records_for_task(task)
    champions = [record for record in records if record.is_champion]
    return {
        "count": len(records),
        "task": task,
        "champions": [record.to_dict() for record in champions],
        "models": [record.to_dict() for record in records],
    }
