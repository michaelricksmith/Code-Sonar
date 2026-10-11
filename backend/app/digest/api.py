"""Digest API: preview, preferences, unsubscribe, and send status.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/digest", tags=["digest"])


class DigestPreferencesRequest(BaseModel):
    digest_enabled: bool = Field(description="Opt in or out of the weekly digest")


def _current_user_id(request: Request) -> str:
    from app.oauth import current_user

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to manage the digest")
    return user.id


@router.get("/preview")
async def digest_preview(request: Request) -> dict[str, Any]:
    """Dry-run: the digest content for the signed-in user, no email sent."""
    from app.digest.preferences import unsubscribe_token
    from app.digest.service import build_digest
    from app.digest.templates import render_html, render_text
    from app.main import get_history_store

    user_id = _current_user_id(request)
    digest = build_digest(user_id, get_history_store())
    if not digest.get("has_activity"):
        return {"has_activity": False, "repos": []}
    token = unsubscribe_token(user_id)
    unsubscribe_url = (
        "https://code-sonar.onrender.com/api/digest/unsubscribe?token=" + token
    )
    return {
        **digest,
        "email_text": render_text(digest, unsubscribe_url),
        "email_html": render_html(digest, unsubscribe_url),
    }


@router.get("/status")
async def digest_status(request: Request) -> dict[str, Any]:
    """Whether digest sending is configured and the user's preference."""
    from app.digest.preferences import get_email_preference_store
    from app.digest.resend_client import is_configured

    user_id = _current_user_id(request)
    return {
        "sending_configured": is_configured(),
        "digest_enabled": get_email_preference_store().is_digest_enabled(user_id),
    }


@router.post("/preferences")
async def set_digest_preferences(
    request: Request, body: DigestPreferencesRequest
) -> dict[str, Any]:
    """Opt in or out of the weekly digest."""
    from app.digest.preferences import get_email_preference_store

    user_id = _current_user_id(request)
    get_email_preference_store().set_digest_enabled(user_id, body.digest_enabled)
    return {"ok": True, "digest_enabled": body.digest_enabled}


@router.get("/unsubscribe")
async def digest_unsubscribe(token: str = Query(min_length=1)) -> dict[str, Any]:
    """One-tap unsubscribe. Token-signed, no sign-in required."""
    from app.digest.preferences import (
        get_email_preference_store,
        verify_unsubscribe_token,
    )

    user_id = verify_unsubscribe_token(token)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link")
    get_email_preference_store().set_digest_enabled(user_id, False)
    return {"ok": True, "message": "You are unsubscribed from the weekly digest."}
