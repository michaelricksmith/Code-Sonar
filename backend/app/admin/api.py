"""Admin console HTTP surface: team management for admins.

Lets an admin list users and grant/revoke the staff (unlimited testing
quota) and admin flags. Every endpoint requires the caller to be an
admin; the flags themselves are never exposed to non-admins.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

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


class PlanRequest(BaseModel):
    plan: str


def _apply_flag(user_id: str, kind: str, value: bool) -> OAuthUser:
    store = get_oauth_user_store()
    setter = getattr(store, f"set_{kind}", None)
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


@router.post("/users/{user_id}/plan")
async def set_user_plan(user_id: str, body: PlanRequest, request: Request) -> dict[str, Any]:
    """Set a user's billing plan directly (free/hobby/plus), no Stripe needed.

    Lets admins grant free pro-tier access. The plan name must be a known
    tier; unknown values fall back to free-tier limits server-side, so we
    reject them here.
    """
    from app.billing.plans import PLAN_FREE, PLAN_HOBBY, PLAN_PLUS

    require_admin(request)
    plan = body.plan.strip().lower()
    if plan not in (PLAN_FREE, PLAN_HOBBY, PLAN_PLUS):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown plan {body.plan!r}; use free, hobby, or plus",
        )
    store = get_oauth_user_store()
    updated = store.set_billing(user_id, plan=plan, stripe_customer_id="")
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": _admin_user_view(updated)}


@router.post("/users/{user_id}/usage/reset")
async def reset_user_usage(user_id: str, request: Request) -> dict[str, Any]:
    """Zero a user's current-period usage counters (fresh quota grant)."""
    require_admin(request)
    if get_oauth_user_store().get(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    usage = get_usage_store().reset_usage(user_id)
    return {"usage": usage}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> dict[str, Any]:
    """Permanently delete a user and their usage counters.

    Guards: an admin cannot delete themselves, and the last remaining
    admin cannot be deleted. The user's scan history is left intact
    (it is keyed by scan id, not user id) — only the account and its
    quota counters are removed.
    """
    caller = require_admin(request)
    if user_id == caller.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    target = get_oauth_user_store().get(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if getattr(target, "is_admin", False):
        admins = [u for u in _all_users() if getattr(u, "is_admin", False) and u.id != user_id]
        if not admins:
            raise HTTPException(status_code=400, detail="Cannot delete the last remaining admin")
    get_oauth_user_store().delete_user(user_id)
    get_usage_store().reset_usage(user_id)
    return {"deleted": user_id}
