"""HTTP surface for recording observed remediation outcomes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ml.outcomes.labels import remediation_success_label
from app.ml.outcomes.runtime import get_outcome_store
from app.ml.outcomes.schema import RemediationOutcome

router = APIRouter(prefix="/remediation-outcomes", tags=["ml-remediation-outcomes"])


class RemediationOutcomeRequest(BaseModel):
    outcome_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    before_scan_id: str = Field(min_length=1)
    after_scan_id: str = Field(min_length=1)
    attempted_at: str = Field(min_length=1)
    executor: str = Field(min_length=1)
    remediation_kind: str = Field(min_length=1)
    build_passed: bool | None = None
    tests_passed: bool | None = None
    finding_resolved: bool
    finding_reintroduced: bool = False
    regression_detected: bool = False
    score_delta: int = 0
    debt_points_delta: int = 0


@router.post("")
async def record_remediation_outcome(request: RemediationOutcomeRequest) -> dict[str, Any]:
    """Persist completed remediation evidence; never execute remediation here."""
    store = get_outcome_store()
    if store.get(request.outcome_id) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "remediation_outcome_exists",
                "outcome_id": request.outcome_id,
            },
        )

    outcome = RemediationOutcome(**request.model_dump())
    store.append(outcome)
    label = remediation_success_label(outcome)
    return {
        "outcome": outcome.to_dict(),
        "training_label": label.to_dict(),
        "deterministic_score_unchanged": True,
        "execution_performed": False,
    }


@router.get("/{outcome_id}")
async def get_remediation_outcome(outcome_id: str) -> dict[str, Any]:
    outcome = get_outcome_store().get(outcome_id)
    if outcome is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "remediation_outcome_not_found", "outcome_id": outcome_id},
        )
    return outcome.to_dict()
