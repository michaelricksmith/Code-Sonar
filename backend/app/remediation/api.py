"""HTTP surface for controlled remediation execution and validation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.remediation.contracts import RemediationRequest
from app.remediation.runtime import (
    get_remediation_executor,
    get_remediation_orchestrator,
    get_validation_service,
    get_workspace_manager,
)

router = APIRouter(prefix="/api/remediation", tags=["remediation"])


class RemediationExecuteRequest(BaseModel):
    request_id: str = Field(min_length=1)
    repository_path: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    scan_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=4000)
    approved: bool = False


class RemediationValidateRequest(BaseModel):
    request_id: str = Field(min_length=1)
    workspace_path: str = Field(min_length=1)
    before_scan_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    executor: str = Field(min_length=1)
    remediation_kind: str = Field(default="automated_patch", min_length=1)


class RemediationRunRequest(RemediationExecuteRequest):
    remediation_kind: str = Field(default="automated_patch", min_length=1)


@router.get("/status")
async def remediation_status() -> dict[str, Any]:
    executor = get_remediation_executor()
    validation = get_validation_service()
    return {
        "executor_name": executor.executor_name,
        "dry_run_default": executor.executor_name == "dry_run",
        "isolated_workspace_required": True,
        "single_call_orchestration_available": True,
        "validation_command_count": len(validation.commands),
        "validation_commands": [
            {"name": command.name, "kind": command.kind}
            for command in validation.commands
        ],
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


@router.post("/validate")
async def validate_remediation(request: RemediationValidateRequest) -> dict[str, Any]:
    """Run configured validators, rescan the worktree, and persist outcome evidence."""
    try:
        result = get_validation_service().validate(**request.model_dump())
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "remediation_validation_workspace_forbidden", "message": str(exc)},
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "remediation_validation_source_not_found", "message": str(exc)},
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "remediation_outcome_exists", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "remediation_validation_invalid", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "remediation_validation_failed",
                "message": "Remediation validation or rescan failed",
            },
        ) from exc

    return {
        "validation": result.to_dict(),
        "active_checkout_modified": False,
        "outcome_recorded": True,
        "deterministic_score_authority": "code_sonar",
    }


@router.post("/run")
async def run_remediation_workflow(request: RemediationRunRequest) -> dict[str, Any]:
    """Prepare, execute, validate, rescan, and record one approved remediation."""
    execution_request = RemediationRequest(
        request_id=request.request_id,
        repository_path=request.repository_path,
        finding_id=request.finding_id,
        scan_id=request.scan_id,
        instruction=request.instruction,
        approved=request.approved,
    )
    try:
        result = get_remediation_orchestrator().run(
            execution_request,
            remediation_kind=request.remediation_kind,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "remediation_approval_required", "message": str(exc)},
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "remediation_source_not_found", "message": str(exc)},
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "remediation_conflict", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "remediation_invalid", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "remediation_workflow_failed", "message": str(exc)},
        ) from exc

    return {"workflow": result.to_dict()}
