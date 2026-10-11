"""Security events API: recent activity for the signed-in user.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/events")
async def security_events(
    request: Request, limit: int = Query(default=20, ge=1, le=100)
) -> dict[str, Any]:
    """Recent security events for the signed-in user (logins, 2FA, etc.)."""
    from app.oauth import current_user
    from app.security_events.events import get_security_event_store

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to view security events")
    events = get_security_event_store().list_for_user(user.id, limit=limit)
    return {
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "created_at": e.created_at,
                "ip_address": e.ip_address,
                "metadata": e.metadata,
                "is_new_device": e.event_type == "new_device_login",
            }
            for e in events
        ]
    }
