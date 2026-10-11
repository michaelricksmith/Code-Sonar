"""Fix-tracking API: per-user fix stats for reports and the digest.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.fix_tracking.service import user_fix_stats

router = APIRouter(prefix="/api/fix-tracking", tags=["fix-tracking"])


@router.get("/stats")
async def fix_stats(request: Request) -> dict[str, Any]:
    """Per-user verified-fix stats: totals, this week, best week, per repo."""
    from app.oauth import current_user

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to view fix stats")
    return user_fix_stats(user.id)
