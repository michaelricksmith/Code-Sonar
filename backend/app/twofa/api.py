"""Two-factor authentication API (TOTP).

Copyright © 2026 Michael Smith. All rights reserved.

Enrollment is a two-step flow: ``POST /enroll`` generates the secret and
QR code, ``POST /confirm`` activates it after the user proves they can
produce codes. Login verification happens through
``POST /verify-login`` with the short-lived pending token the OAuth
callback sets when the account has 2FA enabled.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/2fa", tags=["2fa"])

_PENDING_TTL_SECONDS = 5 * 60
_PENDING_COOKIE = "sonar_2fa_pending"


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    # For email/password logins the pending token arrives in the body
    # (no cookie yet); OAuth logins carry it as a cookie.
    pending_token: str | None = Field(default=None, max_length=1024)


def _session_secret() -> str:
    from app.oauth import _session_secret

    return _session_secret()


def new_pending_token(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "purpose": "2fa_pending", "iat": now,
         "exp": now + _PENDING_TTL_SECONDS},
        _session_secret(),
        algorithm="HS256",
    )


def verify_pending_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, _session_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != "2fa_pending":
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


def _current_user_id(request: Request) -> str:
    from app.oauth import current_user

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to manage 2FA")
    return user.id


@router.get("/status")
async def twofa_status(request: Request) -> dict[str, Any]:
    """Whether the signed-in user has 2FA enabled."""
    from app.twofa.store import get_two_factor_store

    user_id = _current_user_id(request)
    record = get_two_factor_store().get(user_id)
    return {
        "enabled": bool(record and record.enabled),
        "enrolled_at": record.enrolled_at if record else None,
        "backup_codes_remaining": (
            len(record.backup_code_hashes) if record else 0
        ),
    }


@router.post("/enroll")
async def twofa_enroll(request: Request) -> dict[str, Any]:
    """Start enrollment: generate a secret and QR code.

    The secret is stored pending; 2FA is NOT enabled until /confirm
    verifies a code. Re-enrolling replaces the pending secret.
    """
    from app.oauth import get_oauth_user_store
    from app.twofa import totp
    from app.twofa.store import get_two_factor_store

    user_id = _current_user_id(request)
    store = get_two_factor_store()
    existing = store.get(user_id)
    if existing and existing.enabled:
        raise HTTPException(status_code=409, detail="2FA is already enabled")
    user = get_oauth_user_store().get(user_id)
    account = (user.email or user.id) if user else user_id
    secret = totp.generate_secret()
    store.save_pending(user_id, secret)
    uri = totp.otpauth_uri(secret, account)
    return {
        "otpauth_uri": uri,
        "qr_svg": totp.qr_svg(uri),
        "manual_entry_code": secret,
    }


@router.post("/confirm")
async def twofa_confirm(request: Request, body: CodeRequest) -> dict[str, Any]:
    """Verify a code against the pending secret and enable 2FA."""
    from app.twofa import totp
    from app.twofa.store import get_two_factor_store

    user_id = _current_user_id(request)
    store = get_two_factor_store()
    secret = store.get_secret(user_id)
    if not secret:
        raise HTTPException(status_code=400, detail="No pending enrollment")
    if not totp.verify_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    backup_codes = totp.generate_backup_codes()
    store.enable(
        user_id, [totp.hash_backup_code(c) for c in backup_codes]
    )
    from app.security_events.events import TWO_FA_ENROLLED, log_event

    log_event(TWO_FA_ENROLLED, user_id=user_id)
    return {
        "enabled": True,
        "backup_codes": backup_codes,
        "warning": "Save these backup codes now. Each works once.",
    }


@router.post("/disable")
async def twofa_disable(request: Request, body: CodeRequest) -> dict[str, Any]:
    """Disable 2FA after verifying a current code."""
    from app.twofa.store import get_two_factor_store, verify_login_code

    user_id = _current_user_id(request)
    store = get_two_factor_store()
    record = store.get(user_id)
    if not record or not record.enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    ok, _ = verify_login_code(user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid code")
    store.disable(user_id)
    from app.security_events.events import TWO_FA_DISABLED, log_event

    log_event(TWO_FA_DISABLED, user_id=user_id)
    return {"enabled": False}


@router.post("/verify-login")
async def twofa_verify_login(request: Request, body: CodeRequest) -> Response:
    """Complete login with a TOTP or backup code.

    Called from the /2fa/verify page with the pending-token cookie the
    OAuth callback set. On success, issues the real session cookie.
    """
    from app.oauth import _set_session_cookie, get_oauth_user_store
    from app.twofa.store import get_two_factor_store, verify_login_code

    pending = body.pending_token or request.cookies.get(_PENDING_COOKIE)
    user_id = verify_pending_token(pending)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Login session expired")
    user = get_oauth_user_store().get(user_id)
    if user is None or user.is_suspended:
        raise HTTPException(status_code=403, detail="Account unavailable")
    record = get_two_factor_store().get(user_id)
    if not record or not record.enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    ok, method = verify_login_code(user_id, body.code)
    if not ok:
        detail = (
            "Too many failed attempts. Try again in 15 minutes."
            if method == "locked"
            else "Invalid code."
        )
        raise HTTPException(status_code=400, detail=detail)
    from app.oauth import oauth_config
    from app.security_events.events import log_login_success

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    log_login_success(
        user_id,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
        provider="oauth",
        with_2fa=True,
    )
    response = Response(status_code=204)
    _set_session_cookie(response, user_id, oauth_config().session_secret, request)
    response.delete_cookie(_PENDING_COOKIE, path="/")
    return response
