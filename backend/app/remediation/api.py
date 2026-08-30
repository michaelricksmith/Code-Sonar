"""HTTP surface for controlled remediation execution."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.remediation.contracts import RemediationRequest
from app.remediation.runtime import get_remediation_executor

router = APIRouter(prefix="/api/remediation", tags=["remediation"])


class RemediationExecuteRequest(BaseModel):
    request_id: str = Field(min_length=1)
    repository_path: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    scan_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=4000)
    approved: bool = False


@router.get("/status")
async def remediation_status() -> dict[str, Any]:
    executor = get_remediation_executor()
    return {
        "executor_name": executor.executor_name,
        "dry_run_default": executor.executor_name == "dry_run",
        "deterministic_score_authority": "code_sonar",
    }


@router.post("/execute")
async def execute_remediation(request: RemediationExecuteRequest) -> dict[str, Any]:
    """Invoke only the explicitly registered executor for one approved target."""
    execution_request = RemediationRequest(**request.model_dump())
    result = get_remediation_executor().execute(execution_request)
    return {
        "request": execution_request.to_dict(),
        "result": result.to_dict(),
        "deterministic_score_unchanged": True,
    }
