"""HTTP surface for Code Sonar ML metadata, predictions, and similarity."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ml.runtime import (
    get_features_for_scan,
    get_model_registry,
    get_prediction_model,
    get_similarity_index,
)

router = APIRouter(prefix="/api/ml", tags=["ml"])


class PredictionRequest(BaseModel):
    """Request a prediction for an already-persisted Code Sonar scan."""

    scan_id: str = Field(min_length=1)
    task: str = Field(default="debt_risk", min_length=1)


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


@router.post("/predict")
async def predict(request: PredictionRequest) -> dict[str, Any]:
    """Predict from a stored scan using an explicitly loaded fitted model.

    This endpoint never trains a model, never triggers a repository scan, and
    never changes the deterministic Code Sonar score.
    """
    model = get_prediction_model(request.task)
    if model is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ml_model_unavailable",
                "task": request.task,
                "message": "No fitted prediction model is loaded for this task",
            },
        )

    features = get_features_for_scan(request.scan_id)
    if features is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "scan_features_not_found",
                "scan_id": request.scan_id,
                "message": "No persisted scan features were found for this scan_id",
            },
        )

    try:
        prediction = model.predict(features)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ml_model_not_ready",
                "task": request.task,
                "message": str(exc),
            },
        ) from exc

    return {
        "scan_id": request.scan_id,
        "task": request.task,
        "advisory_only": True,
        "deterministic_score_unchanged": True,
        "prediction": prediction.to_dict(),
    }


@router.get("/similar-scans/{scan_id}")
async def similar_scans(
    scan_id: str,
    task: str = Query(default="debt_risk", min_length=1),
    limit: int = Query(default=5, ge=1, le=25),
) -> dict[str, Any]:
    """Return historical scans nearest to a stored scan feature vector."""
    index = get_similarity_index(task)
    if index is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "similarity_index_unavailable",
                "task": task,
                "message": "No fitted similarity index is loaded for this task",
            },
        )

    features = get_features_for_scan(scan_id)
    if features is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "scan_features_not_found",
                "scan_id": scan_id,
                "message": "No persisted scan features were found for this scan_id",
            },
        )

    try:
        cases = index.query(features, limit=limit, exclude_scan_id=scan_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "similarity_index_not_ready",
                "task": task,
                "message": str(exc),
            },
        ) from exc

    return {
        "scan_id": scan_id,
        "task": task,
        "count": len(cases),
        "advisory_only": True,
        "deterministic_score_unchanged": True,
        "similar_scans": [case.to_dict() for case in cases],
    }
