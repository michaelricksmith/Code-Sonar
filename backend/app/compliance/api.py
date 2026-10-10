"""Consumer-compliance HTTP surface: age gate, marketing consent, GPC, and
one-click unsubscribe.

Age gating: sign-up is OAuth-only, so the gate runs on first sign-in. The
question is neutral ("What year were you born?") and the birth year is never
stored — only the age bracket needed to enforce the 13+/18+ minimums. A
user who reports under 13 gets their just-created account scrubbed via
``/age-gate/block``; no record of the attempt is retained.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.compliance import email as email_module
from app.compliance.records import (
    AGE_GATE,
    GPC_OPTOUT,
    MARKETING_CONSENT,
    get_compliance_store,
)
from app.compliance.reminders import due_annual_reminders
from app.oauth import get_oauth_user_store, require_user

router = APIRouter(prefix="/api/compliance", tags=["compliance"])

MIN_ACCOUNT_AGE = 13
MIN_PAID_AGE = 18


class AgeGateRequest(BaseModel):
    birth_year: int = Field(ge=1900, le=2100)


class MarketingConsentRequest(BaseModel):
    opt_in: bool


class GpcRequest(BaseModel):
    gpc: bool


def _age_for_birth_year(birth_year: int) -> int:
    return dt.date.today().year - birth_year


@router.get("/status")
async def compliance_status(request: Request) -> dict[str, Any]:
    """What the client needs to decide whether to show the age gate."""
    user = require_user(request)
    store = get_compliance_store()
    age_gate = store.latest(user.id, AGE_GATE)
    marketing = store.latest(user.id, MARKETING_CONSENT)
    gpc = store.latest(user.id, GPC_OPTOUT)
    return {
        "age_gate_completed": age_gate is not None,
        "age_bracket": (age_gate.payload.get("bracket") if age_gate else None),
        "marketing_opt_in": bool(marketing.payload.get("opt_in")) if marketing else False,
        "gpc_honored": gpc is not None,
    }


@router.post("/age-gate")
async def submit_age_gate(request: Request, body: AgeGateRequest) -> dict[str, Any]:
    """Neutral age gate. Birth year is validated but never stored."""
    user = require_user(request)
    age = _age_for_birth_year(body.birth_year)
    if age < MIN_ACCOUNT_AGE:
        raise HTTPException(
            status_code=403,
            detail={"blocked": True, "reason": "under_13"},
        )
    bracket = "18+" if age >= MIN_PAID_AGE else "13-17"
    record = get_compliance_store().append(
        user_id=user.id,
        record_type=AGE_GATE,
        payload={"bracket": bracket, "minimums": {"account": 13, "paid": 18}},
    )
    return {"ok": True, "bracket": bracket, "confirmed_at": record.created_at}


@router.post("/age-gate/block")
async def block_underage_account(request: Request) -> dict[str, bool]:
    """Delete a just-created under-13 account. No attempt record is kept."""
    user = require_user(request)
    store = get_oauth_user_store()
    scrub = getattr(store, "scrub_underage", None)
    if not callable(scrub):
        raise HTTPException(status_code=501, detail="Account scrub not supported")
    return {"scrubbed": bool(scrub(user.id))}


@router.post("/marketing-consent")
async def set_marketing_consent(
    request: Request, body: MarketingConsentRequest
) -> dict[str, bool]:
    """Record marketing-email opt-in / opt-out. Unchecked by default."""
    user = require_user(request)
    get_compliance_store().append(
        user_id=user.id,
        record_type=MARKETING_CONSENT,
        payload={"opt_in": bool(body.opt_in)},
    )
    return {"opt_in": bool(body.opt_in)}


@router.post("/gpc")
async def report_gpc(request: Request, body: GpcRequest) -> dict[str, bool]:
    """Honor a Global Privacy Control signal as an opt-out of sale/share.

    Code Sonar does not sell personal information or share it for
    cross-context behavioral advertising, so honoring the signal is
    confirmatory — recorded here as proof the signal was seen and honored.
    """
    user = require_user(request)
    if body.gpc:
        get_compliance_store().append(
            user_id=user.id,
            record_type=GPC_OPTOUT,
            payload={
                "gpc": True,
                "honored": True,
                "posture": "no-sale: no ad tech, no data sale, no cross-context sharing",
            },
        )
    return {"honored": True}


@router.post("/unsubscribe/{token}")
async def one_click_unsubscribe(token: str) -> dict[str, bool]:
    """RFC 8058 one-click unsubscribe. No auth: the token is HMAC-signed."""
    user_id = email_module.verify_unsubscribe_token(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe token")
    get_compliance_store().append(
        user_id=user_id,
        record_type=MARKETING_CONSENT,
        payload={"opt_in": False, "via": "one-click-unsubscribe"},
    )
    return {"unsubscribed": True}


@router.get("/reminders/annual")
async def annual_reminders_due(request: Request) -> dict[str, Any]:
    """Admin: paid users due their CA AB 2863 annual renewal reminder.

    Operators run ``scripts/annual_reminders.py --send`` on a schedule
    (monthly is fine); it sends ``annual_renewal_reminder_email`` to each
    due user and appends an ``annual_reminder_sent`` record.
    """
    user = require_user(request)
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin only")
    store = get_oauth_user_store()
    users: list[Any] = []
    if hasattr(store, "list_users"):
        offset = 0
        while True:
            page = store.list_users(limit=500, offset=offset)
            if not page:
                break
            users.extend(page)
            offset += len(page)
    elif hasattr(store, "load_all"):
        users = store.load_all()
    due = due_annual_reminders(users)
    return {
        "due_count": len(due),
        "due": [
            {
                "user_id": d["user_id"],
                "email": d["email"],
                "plan": d["plan"],
                "amount": d["amount"],
                "last_reminder_at": d["last_reminder_at"],
            }
            for d in due
        ],
        "mechanism": "scripts/annual_reminders.py --send",
    }
