"""HTTP surface for controlled remediation execution."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.remediation.contracts import RemediationRequest
from app.remediation.runtime import get_remediation_executor, get_workspace_manager

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
        "isolated_workspace_required": True,
        "deterministic_score_authority": "code_sonar",
    }


@router.post("/workspace/prepare")
async def prepare_remediation_workspace(request: RemediationExecuteRequest) -> dict[str, Any]:
    """Create an isolated Git branch/worktree for an explicitly approved request."""
    execution_request = RemediationRequest(**request.model_dump())
    try:
        workspace = get_workspace_manager().prepare(execution_request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "remediation_approval_required", "message": str(exc)},
        ) from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "remediation_workspace_unavailable", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "remediation_workspace_failed", "message": str(exc)},
        ) from exc

    return {
        "request": execution_request.to_dict(),
        "workspace": workspace.to_dict(),
        "execution_performed": False,
        "active_checkout_modified": False,
        "deterministic_score_unchanged": True,
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
