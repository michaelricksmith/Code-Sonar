"""Quota enforcement for metered Code Sonar features.

``check_quota`` raises HTTP 402 with an ``upgrade_required`` payload when a
user has exhausted their monthly allowance. Anonymous callers (``user_id``
None) are metered against the free tier under the "anonymous" sentinel id.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.billing.plans import PLAN_FREE, limits_for
from app.billing.usage import UsageKind, get_usage_store
from app.oauth import get_oauth_user_store

_LIMIT_KEY: dict[UsageKind, str] = {
    "scans": "scans_per_month",
    "ask_sonar": "ask_sonar_per_month",
}
_USED_KEY: dict[UsageKind, str] = {
    "scans": "scans_used",
    "ask_sonar": "ask_sonar_used",
}


def check_quota(user_id: str | None, kind: UsageKind) -> None:
    """Raise 402 when the user hit their monthly quota for ``kind``.

    The plan resolves from the user store; a missing user id or an
    unknown plan string both fall back to free-tier limits.
    """
    plan = PLAN_FREE
    if user_id is not None:
        user = get_oauth_user_store().get(user_id)
        if user is not None and user.plan:
            plan = user.plan
    limits = limits_for(plan)
    limit = int(limits[_LIMIT_KEY[kind]])
    used = int(get_usage_store().get_usage(user_id)[_USED_KEY[kind]])
    if used >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "upgrade_required": True,
                "kind": kind,
                "plan": plan,
                "limit": limit,
                "used": used,
            },
        )
