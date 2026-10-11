"""Session management API: list, refresh, and revoke sessions.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(tags=["sessions"])


def _current_user_id(request: Request) -> str:
    from app.oauth import current_user

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to manage sessions")
    return user.id


@router.post("/api/auth/refresh")
async def refresh_session(request: Request, response: Response) -> dict[str, Any]:
    """Rotate the refresh token and issue a new short-lived access token.

    The refresh cookie carries ``<session_id>.<refresh_token>``. On
    success the old refresh token is dead (rotation) and both cookies
    are re-issued.
    """
    from app.oauth import _REFRESH_COOKIE, _SESSION_COOKIE, _session_secret
    from app.sessions.sessions import (
        get_session_store,
        hash_refresh_token,
        new_access_token,
        new_refresh_token,
    )

    raw = request.cookies.get(_REFRESH_COOKIE)
    if not raw or "." not in raw:
        raise HTTPException(status_code=401, detail="No refresh token")
    session_id, refresh_token = raw.split(".", 1)
    store = get_session_store()
    # SQL store path: look up by session id + hash comparison.
    session = None
    get_by_both = getattr(store, "get_by_session_and_refresh", None)
    if callable(get_by_both):
        session = get_by_both(session_id, hash_refresh_token(refresh_token))
    else:
        candidate = store.get(session_id)
        if (
            candidate is not None
            and not candidate.revoked
            and store.get_refresh_hash(session_id)
            == hash_refresh_token(refresh_token)
        ):
            session = candidate
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    new_token = new_refresh_token()
    if not store.rotate_refresh(session_id, hash_refresh_token(new_token)):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    secret = _session_secret()
    response.set_cookie(
        _SESSION_COOKIE,
        new_access_token(session_id, session.user_id, secret),
        max_age=15 * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        _REFRESH_COOKIE,
        f"{session_id}.{new_token}",
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/auth/refresh",
    )
    store.touch(session_id)
    return {"ok": True}


@router.get("/api/sessions")
async def list_sessions(request: Request) -> dict[str, Any]:
    """Active sessions for the signed-in user, current one marked."""
    from app.oauth import current_session_id
    from app.sessions.sessions import get_session_store

    user_id = _current_user_id(request)
    current_sid = current_session_id(request)
    sessions = get_session_store().list_for_user(user_id)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "last_seen_at": s.last_seen_at,
                "expires_at": s.expires_at,
                "device_info": s.device_info,
                "ip_address": s.ip_address,
                "revoked": s.revoked,
                "is_current": s.session_id == current_sid,
            }
            for s in sessions
            if not s.revoked
        ]
    }


class RevokeRequest(BaseModel):
    pass


@router.post("/api/sessions/{session_id}/revoke")
async def revoke_session(
    request: Request, session_id: str
) -> dict[str, Any]:
    """Revoke one session. You cannot revoke the session you're using."""
    from app.oauth import current_session_id
    from app.security_events.events import SESSION_REVOKED, log_event
    from app.sessions.sessions import get_session_store

    user_id = _current_user_id(request)
    current_sid = current_session_id(request)
    if session_id == current_sid:
        raise HTTPException(
            status_code=400,
            detail="Cannot revoke your current session. Sign out instead.",
        )
    store = get_session_store()
    session = store.get(session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if not store.revoke(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    log_event(SESSION_REVOKED, user_id=user_id, metadata={"session_id": session_id})
    return {"ok": True}


@router.post("/api/sessions/revoke-others")
async def revoke_other_sessions(request: Request) -> dict[str, Any]:
    """Revoke every session except the current one."""
    from app.oauth import current_session_id
    from app.security_events.events import SESSION_REVOKED, log_event
    from app.sessions.sessions import get_session_store

    user_id = _current_user_id(request)
    current_sid = current_session_id(request)
    count = get_session_store().revoke_all_for_user(user_id, current_sid)
    log_event(
        SESSION_REVOKED, user_id=user_id, metadata={"revoked_count": count}
    )
    return {"ok": True, "revoked": count}
