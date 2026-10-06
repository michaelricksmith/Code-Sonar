"""Admin console HTTP surface: team management for admins.

Lets an admin list users and grant/revoke the staff (unlimited testing
quota) and admin flags. Every endpoint requires the caller to be an
admin; the flags themselves are never exposed to non-admins.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any, Callable, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.billing.usage import get_usage_store
from app.oauth import OAuthUser, get_oauth_user_store, require_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(request: Request) -> OAuthUser:
    user = require_user(request)
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def _all_users() -> list[OAuthUser]:
    store = get_oauth_user_store()
    if hasattr(store, "list_users"):
        users: list[OAuthUser] = []
        offset = 0
        while True:
            page = store.list_users(limit=500, offset=offset)
            if not page:
                break
            users.extend(page)
            offset += len(page)
        return users
    if hasattr(store, "load_all"):
        return list(store.load_all())
    return []


def _admin_user_view(user: OAuthUser) -> dict[str, Any]:
    try:
        usage = get_usage_store().get_usage(user.id)
    except Exception:
        usage = {}
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "provider": user.provider,
        "plan": user.plan,
        "status": user.status,
        "is_admin": bool(getattr(user, "is_admin", False)),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "usage": {
            "scans_used": usage.get("scans_used", 0),
            "ask_sonar_used": usage.get("ask_sonar_used", 0),
        },
    }


@router.get("/users")
async def list_users(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Paginated user list for the admin console."""
    require_admin(request)
    all_users = _all_users()
    return {
        "users": [_admin_user_view(u) for u in all_users[offset : offset + limit]],
        "total": len(all_users),
    }


class StaffRequest(BaseModel):
    is_staff: bool


class AdminRequest(BaseModel):
    is_admin: bool


def _apply_flag(user_id: str, kind: str, value: bool) -> OAuthUser:
    store = get_oauth_user_store()
    setter = cast(
        "Callable[[str, bool], OAuthUser | None] | None",
        getattr(store, f"set_{kind}", None),
    )
    if setter is None:
        raise HTTPException(status_code=501, detail="User store does not support flag changes")
    try:
        updated = setter(user_id, value)
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.post("/users/{user_id}/staff")
async def set_user_staff(user_id: str, body: StaffRequest, request: Request) -> dict[str, Any]:
    """Grant or revoke the staff flag (unlimited testing quota)."""
    require_admin(request)
    updated = _apply_flag(user_id, "staff", body.is_staff)
    return {"user": _admin_user_view(updated)}


@router.post("/users/{user_id}/admin")
async def set_user_admin(user_id: str, body: AdminRequest, request: Request) -> dict[str, Any]:
    """Grant or revoke the admin flag.

    Guards: an admin cannot change their own flag (no accidental
    self-lockout), and the last remaining admin cannot be demoted.
    """
    caller = require_admin(request)
    if user_id == caller.id:
        raise HTTPException(status_code=400, detail="You cannot change your own admin flag")
    if not body.is_admin:
        admins = [u for u in _all_users() if getattr(u, "is_admin", False) and u.id != user_id]
        if not admins:
            raise HTTPException(status_code=400, detail="Cannot demote the last remaining admin")
    updated = _apply_flag(user_id, "admin", body.is_admin)
    return {"user": _admin_user_view(updated)}
