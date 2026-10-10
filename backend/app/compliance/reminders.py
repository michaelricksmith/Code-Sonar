"""Annual renewal reminders (CA AB 2863: product, amount/frequency, how to
cancel — sent via the customer's preferred channel, here email).

Reminder cadence: once per ~12 months for every paid subscriber, starting
11 months after their first paid subscription (or after their last
reminder). Each send appends an ``annual_reminder_sent`` record so the
schedule is self-maintaining.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from app.billing.plans import PLAN_FREE
from app.compliance import email as email_module
from app.compliance.records import (
    ANNUAL_REMINDER_SENT,
    ComplianceRecordStore,
    get_compliance_store,
)

REMINDER_INTERVAL_DAYS = 335  # ~11 months: first reminder before the 12-month mark

_PLAN_AMOUNTS = {"hobby": "$7", "plus": "$14"}


class _UserLike(Protocol):
    id: str
    email: str
    plan: str


def _parse_ts(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except (ValueError, TypeError):
        return None


def _cancel_url() -> str:
    import os

    base = os.environ.get("SONAR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/pricing"


def due_annual_reminders(
    users: list[_UserLike],
    store: ComplianceRecordStore | None = None,
) -> list[dict[str, Any]]:
    """Return the paid users owed an annual renewal reminder right now."""
    store = store or get_compliance_store()
    now = dt.datetime.now(dt.timezone.utc)
    due: list[dict[str, Any]] = []
    for user in users:
        plan = (user.plan or PLAN_FREE).strip().lower()
        if plan == PLAN_FREE or not user.email:
            continue
        latest = store.latest(user.id, ANNUAL_REMINDER_SENT)
        sent_at = _parse_ts(latest.created_at) if latest else None
        if sent_at is not None and (now - sent_at).days < REMINDER_INTERVAL_DAYS:
            continue
        due.append(
            {
                "user_id": user.id,
                "email": user.email,
                "plan": plan,
                "amount": _PLAN_AMOUNTS.get(plan, "?"),
                "last_reminder_at": latest.created_at if latest else None,
            }
        )
    return due


def send_annual_reminder(entry: dict[str, Any]) -> dict[str, str]:
    """Send one annual reminder and record it. Returns the transport receipt."""
    plan_name = str(entry["plan"]).capitalize()
    message = email_module.annual_renewal_reminder_email(
        to=str(entry["email"]),
        plan_name=plan_name,
        amount=str(entry["amount"]),
        cancel_url=_cancel_url(),
    )
    receipt = email_module.send_email(message)
    get_compliance_store().append(
        user_id=str(entry["user_id"]),
        record_type=ANNUAL_REMINDER_SENT,
        payload={
            "plan": entry["plan"],
            "amount": entry["amount"],
            "transport": receipt.get("transport"),
        },
    )
    return receipt


def plan_display_name(plan: str) -> str:
    return {"hobby": "Hobby", "plus": "Plus"}.get(plan, plan.capitalize())
