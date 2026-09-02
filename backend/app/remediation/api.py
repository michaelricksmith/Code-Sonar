"""HTTP surface for controlled remediation execution and validation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.remediation.runtime import (
    get_remediation_executor,
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
    workspace_id: str = Field(min_length=1)
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
        "opaque_workspace_ids": True,
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
    """Reject legacy caller-controlled workspace creation."""
    raise _server_authorization_required()


@router.post("/execute")
async def execute_remediation(request: RemediationExecuteRequest) -> dict[str, Any]:
    """Invoke only the explicitly registered executor for one approved target."""
    raise _server_authorization_required()


@router.post("/validate")
async def validate_remediation(request: RemediationValidateRequest) -> dict[str, Any]:
    """Resolve an opaque workspace, validate it, rescan, and persist outcome evidence."""
    raise _server_authorization_required()
    # The implementation below is intentionally unreachable during the
    # compatibility window and will be removed with the legacy request models.
    workspace = get_workspace_manager().get(request.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "remediation_workspace_not_found",
                "message": "Prepared workspace identity was not found on this server",
            },
        )
    if workspace.request_id != request.request_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "remediation_workspace_request_mismatch",
                "message": "Prepared workspace does not belong to this remediation request",
            },
        )

    try:
        result = get_validation_service().validate(
            request_id=request.request_id,
            workspace_path=workspace.workspace_path,
            before_scan_id=request.before_scan_id,
            finding_id=request.finding_id,
            executor=request.executor,
            remediation_kind=request.remediation_kind,
        )
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
        "workspace_id": workspace.workspace_id,
        "active_checkout_modified": False,
        "outcome_recorded": True,
        "host_paths_exposed": False,
        "deterministic_score_authority": "code_sonar",
    }


@router.post("/run")
async def run_remediation_workflow(request: RemediationRunRequest) -> dict[str, Any]:
    """Reject legacy caller-controlled orchestration."""
    raise _server_authorization_required()


def _server_authorization_required() -> HTTPException:
    return HTTPException(
        status_code=410,
        detail={
            "code": "remediation_server_authorization_required",
            "message": "Use the grounded Ask Sonar approval workflow",
        },
    )
