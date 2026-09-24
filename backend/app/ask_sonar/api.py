"""HTTP surface for grounded Ask Sonar context, answers, and remediation planning."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.ask_sonar.answering import AnswerProviderProtocol, validate_grounded_answer
from app.ask_sonar.context import build_grounding_context
from app.ask_sonar.remediation import build_remediation_plan
from app.ask_sonar.runtime import (
    build_transient_byok_provider,
    get_answer_provider,
    get_provider_registry,
    get_scan,
)
from app.history import ScanRecord
from app.remediation.runtime import (
    get_authorization_service,
    get_remediation_executor,
    get_remediation_orchestrator,
)
from app.remediation.source import resolve_remediation_source
from app.scan_jobs import _github_token_for_request
from app.security.tenant import current_tenant_id

router = APIRouter(prefix="/api/ask-sonar", tags=["ask-sonar"])


class AskSonarRequest(BaseModel):
    """Ask a question about one already-persisted Code Sonar scan."""

    scan_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=4000)
    task: str = Field(default="debt_risk", min_length=1)
    top_findings_limit: int = Field(default=10, ge=1, le=50)
    similar_limit: int = Field(default=3, ge=1, le=20)


class AskSonarRemediationApproval(BaseModel):
    """Explicit approval for one server-derived remediation plan."""

    request_id: str = Field(min_length=1, max_length=200)
    scan_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    approved: bool = False
    remediation_kind: str = Field(default="ask_sonar_approved_patch", min_length=1, max_length=100)


def _require_scan(scan_id: str) -> ScanRecord:
    record = get_scan(scan_id)
    if record is None or record.tenant_id != current_tenant_id():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ask_sonar_scan_not_found",
                "scan_id": scan_id,
                "message": "No persisted scan is available for Ask Sonar grounding",
            },
        )
    return record


@router.get("/status")
async def ask_sonar_status() -> dict[str, Any]:
    """Return configured provider metadata without contacting the provider."""
    provider = get_answer_provider()
    if provider is None:
        return {
            "configured": False,
            "provider": None,
            "model": None,
            "network_checked": False,
            "remediation_planning_available": True,
        }
    return {
        "configured": True,
        "provider": provider.provider_name,
        "model": provider.model_name,
        "network_checked": False,
        "remediation_planning_available": True,
    }


@router.get("/context/{scan_id}")
async def grounding_context(
    scan_id: str,
    task: str = Query(default="debt_risk", min_length=1),
    top_findings_limit: int = Query(default=10, ge=1, le=50),
    similar_limit: int = Query(default=3, ge=1, le=20),
) -> dict[str, Any]:
    """Return a source-separated context bundle for Ask Sonar reasoning."""
    record = _require_scan(scan_id)
    return build_grounding_context(
        record,
        task=task,
        top_findings_limit=top_findings_limit,
        similar_limit=similar_limit,
    )


@router.get("/providers")
async def ask_sonar_providers() -> dict[str, Any]:
    """List available Ask Sonar providers without contacting any of them."""
    return {"providers": get_provider_registry()}


def _resolve_provider(
    x_ai_provider: str | None, x_ai_api_key: str | None
) -> AnswerProviderProtocol | None:
    """Resolve the answer provider: transient BYOK wins over the env default.

    BYOK keys are used for the single request only and are never persisted
    or logged.
    """
    if x_ai_provider is None and x_ai_api_key is None:
        return get_answer_provider()
    try:
        return build_transient_byok_provider(x_ai_provider or "", x_ai_api_key or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ask")
async def ask_sonar(
    request: AskSonarRequest,
    x_ai_provider: str | None = Header(default=None),
    x_ai_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Answer only from the sanitized grounding bundle for the requested scan.

    Optional X-AI-Provider ("openai" | "anthropic") + X-AI-API-Key headers
    select a transient bring-your-own-key provider for this request only.
    """
    provider = _resolve_provider(x_ai_provider, x_ai_api_key)
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ask_sonar_provider_unavailable",
                "message": (
                    "No Ask Sonar answer provider is configured. Set "
                    "ASK_SONAR_PROVIDER=ollama for the self-hosted option, "
                    "ASK_SONAR_PROVIDER=openai with OPENAI_API_KEY, "
                    "ASK_SONAR_PROVIDER=anthropic with ANTHROPIC_API_KEY, "
                    "or pass X-AI-Provider and X-AI-API-Key headers."
                ),
            },
        )

    record = _require_scan(request.scan_id)
    context = build_grounding_context(
        record,
        task=request.task,
        top_findings_limit=request.top_findings_limit,
        similar_limit=request.similar_limit,
    )

    try:
        result = provider.answer(request.question, context)
        result = validate_grounded_answer(result, context)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ask_sonar_grounding_violation",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ask_sonar_provider_failed",
                "message": "The configured Ask Sonar provider failed",
            },
        ) from exc

    return {
        "scan_id": request.scan_id,
        "question": request.question,
        "deterministic_score": record.score,
        "deterministic_grade": record.grade,
        "deterministic_score_unchanged": True,
        "answer": result.to_dict(),
        "grounding": {
            "context_schema_version": context["context_schema_version"],
            "allowed_sources": context["allowed_sources"],
            "source_policy": context["source_policy"],
        },
    }


@router.get("/remediation-plan/{scan_id}/{finding_id}")
async def remediation_plan(scan_id: str, finding_id: str) -> dict[str, Any]:
    """Build a deterministic, approval-gated remediation plan for one finding."""
    record = _require_scan(scan_id)
    try:
        plan = build_remediation_plan(record, finding_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ask_sonar_finding_not_found",
                "message": str(exc),
            },
        ) from exc

    return {
        "plan": plan.to_dict(),
        "approval": {
            "required": True,
            "approved": False,
            "execution_performed": False,
        },
        "deterministic_score": record.score,
        "deterministic_grade": record.grade,
        "deterministic_score_unchanged": True,
    }


@router.post("/remediation/approve-and-run")
async def approve_and_run_remediation(
    request: Request,
    approval: AskSonarRemediationApproval,
) -> dict[str, Any]:
    """Verify an approved grounded plan and hand it to remediation orchestration.

    Hosted scan workspaces are deleted after scanning, so the source checkout
    is re-materialized on demand before the authorization is issued and
    cleaned up after the workflow completes.
    """
    if not approval.approved:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ask_sonar_remediation_approval_required",
                "message": "Explicit user approval is required before remediation execution",
            },
        )

    record = _require_scan(approval.scan_id)
    try:
        plan = build_remediation_plan(record, approval.finding_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "ask_sonar_finding_not_found", "message": str(exc)},
        ) from exc

    if approval.plan_id != plan.plan_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ask_sonar_remediation_plan_mismatch",
                "message": "The approved plan does not match the current grounded plan",
            },
        )

    source = None
    try:
        source = resolve_remediation_source(
            record, github_token=_github_token_for_request(request)
        )
        executor = get_remediation_executor()
        authorization = get_authorization_service().issue(
            request_id=approval.request_id,
            repository_path=source.path,
            scan_id=record.scan_id,
            finding_id=plan.finding_id,
            plan_id=plan.plan_id,
            executor=executor.executor_name,
            remediation_kind=approval.remediation_kind,
            instruction=plan.instruction,
        )
        workflow = get_remediation_orchestrator().run_authorized(authorization)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "ask_sonar_remediation_forbidden", "message": str(exc)},
        ) from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "ask_sonar_remediation_unavailable", "message": str(exc)},
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "ask_sonar_remediation_source_not_found", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "ask_sonar_remediation_failed", "message": str(exc)},
        ) from exc
    finally:
        if source is not None:
            source.dispose()

    return {
        "plan": plan.to_dict(),
        "approval": {
            "required": True,
            "approved": True,
            "request_id": approval.request_id,
        },
        "workflow": workflow.to_dict(),
        "deterministic_score_authority": "code_sonar",
    }
