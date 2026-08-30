"""HTTP surface for grounded Ask Sonar context."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.ask_sonar.context import build_grounding_context
from app.ask_sonar.runtime import get_scan

router = APIRouter(prefix="/api/ask-sonar", tags=["ask-sonar"])


@router.get("/context/{scan_id}")
async def grounding_context(
    scan_id: str,
    task: str = Query(default="debt_risk", min_length=1),
    top_findings_limit: int = Query(default=10, ge=1, le=50),
    similar_limit: int = Query(default=3, ge=1, le=20),
) -> dict[str, Any]:
    """Return a source-separated context bundle for Ask Sonar reasoning."""
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

    return build_grounding_context(
        record,
        task=task,
        top_findings_limit=top_findings_limit,
        similar_limit=similar_limit,
    )
