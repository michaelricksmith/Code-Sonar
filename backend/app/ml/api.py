"""HTTP surface for Code Sonar ML metadata, predictions, similarity, and outcomes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.ml.outcomes.api import router as outcomes_router
from app.ml.runtime import (
    get_features_for_scan,
    get_model_registry,
    get_prediction_model,
    get_similarity_index,
)
from app.security.ownership import assert_scan_access, visible_scans

router = APIRouter(prefix="/api/ml", tags=["ml"])
router.include_router(outcomes_router)


def _assert_scan_id_access(http_request: Request, scan_id: str) -> None:
    """Enforce per-scan ownership for scan-id-addressed ML endpoints.

    The unguessable scan id is a bearer capability; owned scans additionally
    require the owning user. When no record exists there is nothing to
    protect, and the feature layer reports the miss as before.
    """
    from app.main import get_history_store

    record = get_history_store().get(scan_id)
    if record is not None:
        assert_scan_access(record, http_request)


def _filter_visible_cases(http_request: Request, cases: Sequence[Any]) -> list[Any]:
    """Drop similar-scan cases the caller may not enumerate."""
    from app.main import get_history_store

    store = get_history_store()
    records = [r for r in (store.get(c.scan_id) for c in cases) if r is not None]
    visible_ids = {r.scan_id for r in visible_scans(records, http_request)}
    return [c for c in cases if c.scan_id in visible_ids]


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
async def predict(http_request: Request, request: PredictionRequest) -> dict[str, Any]:
    """Predict from a stored scan using an explicitly loaded fitted model.

    This endpoint never trains a model, never triggers a repository scan, and
    never changes the deterministic Code Sonar score.
    """
    _assert_scan_id_access(http_request, request.scan_id)
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
    http_request: Request,
    scan_id: str,
    task: str = Query(default="debt_risk", min_length=1),
    limit: int = Query(default=5, ge=1, le=25),
) -> dict[str, Any]:
    """Return historical scans nearest to a stored scan feature vector."""
    _assert_scan_id_access(http_request, scan_id)
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

    visible_cases = _filter_visible_cases(http_request, cases)
    return {
        "scan_id": scan_id,
        "task": task,
        "count": len(visible_cases),
        "advisory_only": True,
        "deterministic_score_unchanged": True,
        "similar_scans": [case.to_dict() for case in visible_cases],
    }
