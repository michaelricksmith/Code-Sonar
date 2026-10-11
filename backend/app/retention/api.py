"""Retention API: churn nudge for the signed-in user (Phase 4).

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/retention", tags=["retention"])


@router.get("/nudge")
async def retention_nudge(request: Request) -> dict[str, Any]:
    """The user's most urgent tailored nudge, or none when they're active."""
    from app.main import get_history_store
    from app.oauth import current_user
    from app.retention.churn import generate_nudge, user_churn_signals

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to view nudges")
    nudge = generate_nudge(user.id, get_history_store())
    return {
        "nudge": nudge,
        "signals": [s["signal"] for s in user_churn_signals(user.id, get_history_store())],
    }
