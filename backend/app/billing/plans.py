"""Billing plan tiers and their quota limits.

Flat-rate tiers with monthly quotas. Fix prompts are unlimited on every
plan and are therefore not metered anywhere in this package.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from typing import Any

PLAN_FREE = "free"
PLAN_HOBBY = "hobby"
PLAN_PLUS = "plus"

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    PLAN_FREE: {
        "repos": 1,
        "scans_per_month": 5,
        "ask_sonar_per_month": 25,
        "history_days": 7,
        "priority": False,
    },
    PLAN_HOBBY: {
        "repos": 5,
        "scans_per_month": 50,
        "ask_sonar_per_month": 500,
        "history_days": 90,
        "priority": False,
    },
    PLAN_PLUS: {
        "repos": 20,
        "scans_per_month": 300,
        "ask_sonar_per_month": 2000,
        "history_days": None,
        "priority": True,
    },
}


def limits_for(plan: str | None) -> dict[str, Any]:
    """Return the quota limits for a plan name.

    Defensive: unknown, empty, or missing plan strings fall back to the
    free tier. Returns a copy so callers cannot mutate the shared table.
    """
    key = (plan or "").strip().lower()
    return dict(PLAN_LIMITS.get(key, PLAN_LIMITS[PLAN_FREE]))
