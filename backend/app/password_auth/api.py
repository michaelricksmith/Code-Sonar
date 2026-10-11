"""Email/password authentication: signup, login, verification, reset.

Copyright © 2026 Michael Smith. All rights reserved.

Passwords are scrypt-hashed; breach-checked against HaveIBeenPwned at
signup and password change. Email verification and password reset use
single-use tokens delivered by the Resend client (logged locally when
email is not configured). Login honours TOTP 2FA when enrolled.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/auth", tags=["password-auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VERIFY_TOKEN_TTL_HOURS = 24
_RESET_TOKEN_TTL_MINUTES = 60


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(default="", max_length=255)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


def _check_password_policy(password: str) -> None:
    from app.password_auth.passwords import (
        check_password_breached_or_raise,
        validate_password,
    )

    violation = validate_password(password)
    if violation:
        raise HTTPException(status_code=400, detail=violation.reason)
    check_password_breached_or_raise(password)


def _send_email(to: str, subject: str, html: str, text: str) -> bool:
    """Send via Resend when configured; log locally otherwise."""
    from app.digest.resend_client import is_configured, send_email

    if not is_configured():
        import logging

        logging.getLogger("code-sonar.auth").warning(
            "Email not configured; %s email to %s not sent.", subject, to
        )
        return False
    try:
        send_email(to=to, subject=subject, html=html, text=text)
        return True
    except Exception:
        import logging

        logging.getLogger("code-sonar.auth").exception(
            "Failed to send %s email to %s", subject, to
        )
        return False


def _app_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}"


@router.post("/signup")
async def signup(request: Request, body: SignupRequest) -> dict[str, Any]:
    """Create an email/password account and send a verification email."""
    from app.oauth import get_oauth_user_store
    from app.password_auth.passwords import hash_password

    email = _validate_email(body.email)
    _check_password_policy(body.password)
    store = get_oauth_user_store()
    # SqlUserStore has get_by_email; the JSON store does not.
    get_by_email = getattr(store, "get_by_email", None)
    if callable(get_by_email) and get_by_email(email) is not None:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Try signing in.",
        )
    create_email_user = getattr(store, "create_email_user", None)
    if not callable(create_email_user):
        raise HTTPException(
            status_code=503, detail="Email signup is not available right now."
        )
    user = create_email_user(email, body.name.strip(), hash_password(body.password))
    # Verification token.
    token = secrets.token_urlsafe(32)
    store.set_email_verify_token(user.id, _hash_token(token))
    verify_url = _app_url(request, f"/api/auth/verify-email?token={token}")
    _send_email(
        email,
        "Verify your Code Sonar email",
        f"<p>Click to verify your email:</p><p><a href='{verify_url}'>{verify_url}</a></p>"
        "<p>This link expires in 24 hours.</p>",
        f"Verify your email: {verify_url}\nThis link expires in 24 hours.",
    )
    from app.security_events.events import log_event

    log_event("signup", user_id=user.id, metadata={"method": "email"})
    return {"ok": True, "needs_verification": True}


@router.get("/verify-email")
async def verify_email(token: str) -> Response:
    """Verify an email address from the signup link."""
    from fastapi.responses import RedirectResponse

    from app.oauth import get_oauth_user_store

    store = get_oauth_user_store()
    get_by_token = getattr(store, "get_by_verify_token", None)
    if not callable(get_by_token):
        raise HTTPException(status_code=503, detail="Verification unavailable.")
    user = get_by_token(_hash_token(token))
    if user is None:
        raise HTTPException(
            status_code=400, detail="This verification link is invalid or expired."
        )
    store.set_email_verified(user.id, True)
    from app.security_events.events import log_event

    log_event("email_verified", user_id=user.id)
    return RedirectResponse(url="/app?verified=1", status_code=302)


@router.post("/login")
async def login(request: Request, body: LoginRequest) -> Response:
    """Email/password login. Returns a session or a 2FA challenge."""
    from fastapi.responses import JSONResponse

    from app.oauth import _session_secret, _set_session_cookie, get_oauth_user_store
    from app.password_auth.passwords import verify_password
    from app.security_events.events import LOGIN_FAILURE, log_event

    email = _validate_email(body.email)
    store = get_oauth_user_store()
    get_by_email = getattr(store, "get_by_email", None)
    user = get_by_email(email) if callable(get_by_email) else None
    password_hash = (
        store.get_password_hash(user.id)
        if user and hasattr(store, "get_password_hash")
        else None
    )
    if user is None or not password_hash or not verify_password(
        body.password, password_hash
    ):
        log_event(
            LOGIN_FAILURE,
            user_id=user.id if user else None,
            metadata={"method": "email"},
        )
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if hasattr(store, "is_email_verified") and not store.is_email_verified(user.id):
        raise HTTPException(
            status_code=403,
            detail="Verify your email first. Check your inbox for the link.",
        )
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account is suspended.")
    # 2FA challenge when enrolled: the client posts the pending token to
    # /api/2fa/verify-login.
    from app.twofa.api import new_pending_token
    from app.twofa.store import get_two_factor_store

    record = get_two_factor_store().get(user.id)
    if record is not None and record.enabled:
        return JSONResponse(
            content={
                "ok": True,
                "needs_2fa": True,
                "pending_token": new_pending_token(user.id),
            }
        )
    from app.security_events.events import log_login_success

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    log_login_success(
        user.id,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
        provider="email",
    )
    response = JSONResponse(content={"ok": True})
    _set_session_cookie(response, user.id, _session_secret(), request)
    return response


@router.post("/forgot-password")
async def forgot_password(
    request: Request, body: ForgotPasswordRequest
) -> dict[str, Any]:
    """Send a password reset email. Always returns ok (no email leakage)."""
    from app.oauth import get_oauth_user_store

    email = _validate_email(body.email)
    store = get_oauth_user_store()
    get_by_email = getattr(store, "get_by_email", None)
    user = get_by_email(email) if callable(get_by_email) else None
    if user is not None and hasattr(store, "set_password_reset_token"):
        # Only email-auth users can reset a password.
        has_password = (
            store.get_password_hash(user.id)
            if hasattr(store, "get_password_hash")
            else None
        )
        if has_password:
            token = secrets.token_urlsafe(32)
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(minutes=_RESET_TOKEN_TTL_MINUTES)
            ).isoformat()
            store.set_password_reset_token(user.id, _hash_token(token), expires_at)
            reset_url = _app_url(request, f"/reset-password?token={token}")
            _send_email(
                email,
                "Reset your Code Sonar password",
                f"<p>Reset your password:</p><p><a href='{reset_url}'>{reset_url}</a></p>"
                "<p>This link expires in 60 minutes. "
                "If you did not request it, ignore this email.</p>",
                f"Reset your password: {reset_url}\nThis link expires in 60 minutes.",
            )
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest) -> dict[str, Any]:
    """Set a new password from a reset token."""
    from app.oauth import get_oauth_user_store
    from app.password_auth.passwords import hash_password

    _check_password_policy(body.new_password)
    store = get_oauth_user_store()
    get_by_token = getattr(store, "get_by_reset_token", None)
    if not callable(get_by_token):
        raise HTTPException(status_code=503, detail="Password reset unavailable.")
    user = get_by_token(_hash_token(body.token))
    if user is None:
        raise HTTPException(
            status_code=400, detail="This reset link is invalid or expired."
        )
    store.set_password_hash(user.id, hash_password(body.new_password))
    store.set_password_reset_token(user.id, None, None)
    # Revoke all sessions: the password change signs everyone out.
    from app.sessions.sessions import get_session_store

    try:
        get_session_store().revoke_all_for_user(user.id, None)
    except Exception:
        pass
    from app.security_events.events import log_event

    log_event("password_changed", user_id=user.id, metadata={"via": "reset"})
    _send_email(
        user.email,
        "Your Code Sonar password was changed",
        "<p>Your password was just changed. If this was not you, contact support immediately.</p>",
        "Your password was just changed. If this was not you, contact support immediately.",
    )
    return {"ok": True}


@router.post("/change-password")
async def change_password(request: Request, body: ChangePasswordRequest) -> dict[str, Any]:
    """Change password for a signed-in user (verifies the current one)."""
    from app.oauth import current_session_id, current_user, get_oauth_user_store
    from app.password_auth.passwords import hash_password, verify_password

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to change your password.")
    store = get_oauth_user_store()
    if not hasattr(store, "get_password_hash"):
        raise HTTPException(status_code=503, detail="Password change unavailable.")
    current_hash = store.get_password_hash(user.id)
    if not current_hash or not verify_password(body.current_password, current_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    _check_password_policy(body.new_password)
    store.set_password_hash(user.id, hash_password(body.new_password))
    # Keep this session, revoke the rest.
    from app.sessions.sessions import get_session_store

    try:
        get_session_store().revoke_all_for_user(user.id, current_session_id(request))
    except Exception:
        pass
    from app.security_events.events import log_event

    log_event("password_changed", user_id=user.id, metadata={"via": "settings"})
    return {"ok": True}
