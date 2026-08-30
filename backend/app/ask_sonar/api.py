"""HTTP surface for grounded Ask Sonar context and answers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ask_sonar.answering import validate_grounded_answer
from app.ask_sonar.context import build_grounding_context
from app.ask_sonar.runtime import get_answer_provider, get_scan

router = APIRouter(prefix="/api/ask-sonar", tags=["ask-sonar"])


class AskSonarRequest(BaseModel):
    """Ask a question about one already-persisted Code Sonar scan."""

    scan_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=4000)
    task: str = Field(default="debt_risk", min_length=1)
    top_findings_limit: int = Field(default=10, ge=1, le=50)
    similar_limit: int = Field(default=3, ge=1, le=20)


def _require_scan(scan_id: str):
    record = get_scan(scan_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ask_sonar_scan_not_found",
                "scan_id": scan_id,
                "message": "No persisted scan is available for Ask Sonar grounding",
            },
        )
    return record


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


@router.post("/ask")
async def ask_sonar(request: AskSonarRequest) -> dict[str, Any]:
    """Answer only from the sanitized grounding bundle for the requested scan."""
    provider = get_answer_provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ask_sonar_provider_unavailable",
                "message": "No approved Ask Sonar answer provider is configured",
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
