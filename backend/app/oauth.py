"""GitHub + Google OAuth Authorization Code flow for Code Sonar users.

Config comes only from the environment (never hardcoded, never logged):

- GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET
- GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET
- SONAR_PUBLIC_URL (used to build redirect URIs)
- SONAR_SESSION_SECRET (dev fallback is a random per-process secret with a
  loud startup warning)

OAuth access tokens are stored server-side only and are never returned to any
client. When SQL persistence is configured (``CODESONAR_DATABASE_URL``), user
accounts live in the database-backed ``SqlUserStore`` (tokens encrypted at
rest); otherwise they fall back to the local JSON user store under
``~/.code-sonar/`` (mode 0600), which is ephemeral on hosted deployments.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Protocol
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger(__name__)

_SESSION_COOKIE = "sonar_session"
_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
_STATE_TTL_SECONDS = 10 * 60

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_REPOS_URL = "https://api.github.com/user/repos"
_GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# (url, form-or-json-body, headers) -> (status_code, parsed-json-body)
HttpPost = Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any]]]
HttpGet = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


def _default_http_post(
    url: str, body: dict[str, Any], headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    with httpx.Client(timeout=20.0, trust_env=False) as client:
        response = client.post(url, data=body, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload if isinstance(payload, dict) else {}


def _default_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    with httpx.Client(timeout=20.0, trust_env=False) as client:
        response = client.get(url, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, list):
        return response.status_code, {"_items": payload}
    return response.status_code, payload if isinstance(payload, dict) else {}


_http_post: HttpPost = _default_http_post
_http_get: HttpGet = _default_http_get


def set_oauth_transport(http_post: HttpPost | None = None, http_get: HttpGet | None = None) -> None:
    """Override OAuth HTTP calls; primarily used by tests."""
    global _http_post, _http_get
    if http_post is not None:
        _http_post = http_post
    if http_get is not None:
        _http_get = http_get


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    github_client_id: str
    github_client_secret: str
    google_client_id: str
    google_client_secret: str
    public_url: str
    session_secret: str


_secret_warning_emitted = False
_fallback_secret: str | None = None


def _session_secret() -> str:
    global _secret_warning_emitted, _fallback_secret
    configured = os.environ.get("SONAR_SESSION_SECRET", "").strip()
    if configured:
        return configured
    if not _secret_warning_emitted:
        _secret_warning_emitted = True
        print(
            "WARNING: SONAR_SESSION_SECRET is not set; using a random per-process "
            "session secret. All sessions will be invalidated on restart. Set "
            "SONAR_SESSION_SECRET in production.",
            file=sys.stderr,
            flush=True,
        )
    # Cache the fallback for the life of the process: a fresh secret per
    # call would make every issued token unverifiable.
    if _fallback_secret is None:
        _fallback_secret = secrets.token_hex(32)
    return _fallback_secret


def session_secret_configured() -> bool:
    """True when the operator explicitly set SONAR_SESSION_SECRET.

    An explicitly configured session secret means OAuth session-cookie auth is
    available as a production authentication path (no dev flag required).
    """
    return bool(os.environ.get("SONAR_SESSION_SECRET", "").strip())


def oauth_config() -> OAuthConfig:
    return OAuthConfig(
        github_client_id=os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip(),
        github_client_secret=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "").strip(),
        google_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        google_client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        public_url=os.environ.get("SONAR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
        session_secret=_session_secret(),
    )


def _sign_state(raw: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{raw}.{digest}"


def new_state(secret: str) -> str:
    """Issue a stateless, HMAC-signed CSRF state token (10-minute TTL)."""
    raw = secrets.token_urlsafe(32)
    issued_at = str(int(time.time()))
    return _sign_state(f"{raw}.{issued_at}", secret)


def verify_state(state: str | None, secret: str) -> bool:
    if not state:
        return False
    try:
        raw, issued_at, digest = state.rsplit(".", 2)
    except ValueError:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), f"{raw}.{issued_at}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return False
    try:
        age = time.time() - int(issued_at)
    except ValueError:
        return False
    return 0 <= age <= _STATE_TTL_SECONDS


def new_github_connect_state(secret: str, user_id: str) -> str:
    """Issue a signed OAuth state binding a GitHub-connect flow to a user.

    Unlike the login flow (which mints a brand-new session), the connect flow
    attaches the GitHub OAuth token to the already-signed-in account. The
    user id travels inside the HMAC-signed payload so the callback can verify
    the person completing the flow is the one who started it. Same 10-minute
    TTL as login states.
    """
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "mode": "connect",
                    "user_id": user_id,
                    "nonce": secrets.token_urlsafe(16),
                }
            ).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    issued_at = str(int(time.time()))
    return _sign_state(f"{payload}.{issued_at}", secret)


def parse_github_connect_state(state: str | None, secret: str) -> str | None:
    """Return the bound user id when ``state`` is a valid connect state.

    Returns None for login states, tampered states, and expired states.
    """
    if not state:
        return None
    try:
        payload_b64, issued_at, digest = state.rsplit(".", 2)
    except ValueError:
        return None
    expected = hmac.new(
        secret.encode("utf-8"), f"{payload_b64}.{issued_at}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    try:
        age = time.time() - int(issued_at)
    except ValueError:
        return None
    if not 0 <= age <= _STATE_TTL_SECONDS:
        return None
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("mode") != "connect":
        return None
    user_id = payload.get("user_id")
    return str(user_id) if user_id else None


def new_session_token(user_id: str, secret: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + _SESSION_TTL_SECONDS},
        secret,
        algorithm="HS256",
    )


def verify_session_token(token: str, secret: str) -> str | None:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


@dataclass(frozen=True, slots=True)
class OAuthUser:
    id: str
    provider: str
    provider_user_id: str
    name: str
    email: str
    avatar_url: str
    github_access_token: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Database-backed account fields. Defaults keep legacy JSON records
    # (written before these fields existed) loadable.
    github_id: str = ""
    github_username: str = ""
    google_sub: str = ""
    plan: str = "free"
    stripe_customer_id: str = ""
    status: str = "active"
    is_admin: bool = False
    is_staff: bool = False
    last_login_at: str = ""

    @property
    def is_suspended(self) -> bool:
        return self.status != "active"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "provider": self.provider,
        }


class GitHubIdentityConflictError(Exception):
    """A GitHub identity is already linked to a different Code Sonar account.

    The ``users`` table enforces uniqueness on ``github_id``. When the
    account-linking flow tries to attach a GitHub identity that another
    account already owns, stores raise this instead of leaking a raw
    database IntegrityError (500). Callers map it to an honest 409.
    """


class UserStore(Protocol):
    """Structural interface for user account stores.

    ``OAuthUserStore`` (local JSON) and ``SqlUserStore`` (database) both
    satisfy this protocol, so the OAuth callbacks work unchanged against
    either backend.
    """

    def get(self, user_id: str) -> OAuthUser | None: ...
    def upsert(
        self,
        *,
        provider: str,
        provider_user_id: str,
        name: str,
        email: str,
        avatar_url: str,
        github_access_token: str = "",
        github_username: str = "",
    ) -> OAuthUser: ...
    def set_billing(self, user_id: str, *, plan: str, stripe_customer_id: str) -> OAuthUser | None:
        """Update a user's billing plan (and Stripe customer id when given).

        An empty ``stripe_customer_id`` preserves the existing value.
        Returns the updated user, or None when the user does not exist.
        """
        ...

    def scrub_underage(self, user_id: str) -> bool:
        """Delete a just-created under-13 account (age-gate block).

        Removes the entire record — name, email, avatar, OAuth identities,
        tokens, and the signup row itself. No record of the attempt is
        retained. Returns True when a record was deleted.
        """
        ...

    # -- email/password auth (SqlUserStore only; JSON store lacks these) --

    def get_by_email(self, email: str) -> OAuthUser | None: ...
    def create_email_user(
        self, email: str, name: str, password_hash: str
    ) -> OAuthUser: ...
    def get_password_hash(self, user_id: str) -> str | None: ...
    def set_password_hash(self, user_id: str, password_hash: str) -> None: ...
    def is_email_verified(self, user_id: str) -> bool: ...
    def set_email_verified(self, user_id: str, verified: bool = True) -> None: ...
    def set_email_verify_token(
        self, user_id: str, token_hash: str | None
    ) -> None: ...
    def get_by_verify_token(self, token_hash: str) -> OAuthUser | None: ...
    def set_password_reset_token(
        self, user_id: str, token_hash: str | None, expires_at: str | None
    ) -> None: ...
    def get_by_reset_token(self, token_hash: str) -> OAuthUser | None: ...

    def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user record (admin action)."""
        ...

    def get_by_github_id(self, github_id: str) -> OAuthUser | None:
        """Return the account that owns a GitHub identity, or None.

        Used by the account-linking flow to detect a conflict before
        writing: a GitHub identity can belong to exactly one Code Sonar
        account.
        """
        ...

    def link_github(
        self,
        user_id: str,
        *,
        github_id: str,
        github_username: str,
        github_access_token: str,
    ) -> OAuthUser | None:
        """Attach GitHub OAuth credentials to an existing user record.

        Used by the account-linking flow: the user stays on their current
        account (plan, flags, and history untouched) and gains the GitHub
        token needed for repo listing and private-repo clones. Returns the
        updated user, or None when the user does not exist. Raises
        ``GitHubIdentityConflictError`` when the identity is already linked to a
        different account.
        """
        ...

    def unlink_github(self, user_id: str) -> OAuthUser | None:
        """Remove GitHub OAuth credentials from a user record.

        Returns the updated user, or None when the user does not exist.
        """
        ...


def _merge_existing_oauth_user(
    existing: OAuthUser,
    *,
    provider: str,
    provider_user_id: str,
    name: str,
    email: str,
    avatar_url: str,
    github_access_token: str,
    github_username: str,
    now: str,
) -> OAuthUser:
    """Refresh an existing OAuth record with a fresh sign-in.

    Non-empty incoming values win; empty ones keep the stored values.
    """
    return OAuthUser(
        id=existing.id,
        provider=provider,
        provider_user_id=provider_user_id,
        name=name or existing.name,
        email=email or existing.email,
        avatar_url=avatar_url or existing.avatar_url,
        github_access_token=github_access_token or existing.github_access_token,
        created_at=existing.created_at,
        updated_at=now,
        github_id=provider_user_id if provider == "github" else existing.github_id,
        github_username=github_username or existing.github_username,
        google_sub=provider_user_id if provider == "google" else existing.google_sub,
        plan=existing.plan,
        stripe_customer_id=existing.stripe_customer_id,
        status=existing.status,
        is_admin=existing.is_admin,
        is_staff=existing.is_staff,
        last_login_at=now,
    )


def _new_oauth_user(
    *,
    provider: str,
    provider_user_id: str,
    name: str,
    email: str,
    avatar_url: str,
    github_access_token: str,
    github_username: str,
    now: str,
) -> OAuthUser:
    """Build a first-time OAuth record."""
    return OAuthUser(
        id=uuid.uuid4().hex,
        provider=provider,
        provider_user_id=provider_user_id,
        name=name,
        email=email,
        avatar_url=avatar_url,
        github_access_token=github_access_token,
        created_at=now,
        updated_at=now,
        github_id=provider_user_id if provider == "github" else "",
        github_username=github_username,
        google_sub=provider_user_id if provider == "google" else "",
        last_login_at=now,
    )


class OAuthUserStore:
    """Server-side user + OAuth token store (JSON, mode 0600).

    OAuth tokens never leave the server; clients only ever see the public
    profile projection.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "oauth-users.json")
        self._lock = RLock()

    def _load(self) -> list[OAuthUser]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [OAuthUser(**item) for item in payload]

    def load_all(self) -> list[OAuthUser]:
        """Return every stored user. Used by the one-time DB import."""
        with self._lock:
            return self._load()

    def _save(self, records: list[OAuthUser]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)

    def get(self, user_id: str) -> OAuthUser | None:
        with self._lock:
            return next((u for u in self._load() if u.id == user_id), None)

    def get_by_github_id(self, github_id: str) -> OAuthUser | None:
        if not github_id:
            return None
        with self._lock:
            return next((u for u in self._load() if u.github_id == github_id), None)

    def upsert(
        self,
        *,
        provider: str,
        provider_user_id: str,
        name: str,
        email: str,
        avatar_url: str,
        github_access_token: str = "",
        github_username: str = "",
    ) -> OAuthUser:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            for index, existing in enumerate(records):
                if existing.provider == provider and existing.provider_user_id == provider_user_id:
                    updated = _merge_existing_oauth_user(
                        existing,
                        provider=provider,
                        provider_user_id=provider_user_id,
                        name=name,
                        email=email,
                        avatar_url=avatar_url,
                        github_access_token=github_access_token,
                        github_username=github_username,
                        now=now,
                    )
                    records[index] = updated
                    self._save(records)
                    return updated
            user = _new_oauth_user(
                provider=provider,
                provider_user_id=provider_user_id,
                name=name,
                email=email,
                avatar_url=avatar_url,
                github_access_token=github_access_token,
                github_username=github_username,
                now=now,
            )
            records.append(user)
            self._save(records)
            return user

    def set_billing(self, user_id: str, *, plan: str, stripe_customer_id: str) -> OAuthUser | None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            for index, existing in enumerate(records):
                if existing.id == user_id:
                    updated = replace(
                        existing,
                        plan=plan,
                        stripe_customer_id=stripe_customer_id or existing.stripe_customer_id,
                        updated_at=now,
                    )
                    records[index] = updated
                    self._save(records)
                    return updated
        return None

    def set_staff(self, user_id: str, is_staff: bool) -> OAuthUser | None:
        """Grant or revoke the staff flag (unlimited testing quota)."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            for index, existing in enumerate(records):
                if existing.id == user_id:
                    updated = replace(existing, is_staff=is_staff, updated_at=now)
                    records[index] = updated
                    self._save(records)
                    return updated
        return None

    def set_admin(self, user_id: str, is_admin: bool) -> OAuthUser | None:
        """Grant or revoke the admin flag."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            for index, existing in enumerate(records):
                if existing.id == user_id:
                    updated = replace(existing, is_admin=is_admin, updated_at=now)
                    records[index] = updated
                    self._save(records)
                    return updated
        return None

    def link_github(
        self,
        user_id: str,
        *,
        github_id: str,
        github_username: str,
        github_access_token: str,
    ) -> OAuthUser | None:
        """Attach GitHub OAuth credentials to an existing user record."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            if github_id:
                owner = next(
                    (u for u in records if u.github_id == github_id and u.id != user_id),
                    None,
                )
                if owner is not None:
                    raise GitHubIdentityConflictError(
                        "GitHub identity is already linked to a different account"
                    )
            for index, existing in enumerate(records):
                if existing.id == user_id:
                    updated = replace(
                        existing,
                        github_id=github_id,
                        github_username=github_username,
                        github_access_token=github_access_token,
                        updated_at=now,
                    )
                    records[index] = updated
                    self._save(records)
                    return updated
        return None

    def unlink_github(self, user_id: str) -> OAuthUser | None:
        """Remove GitHub OAuth credentials from a user record."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            for index, existing in enumerate(records):
                if existing.id == user_id:
                    updated = replace(
                        existing,
                        github_id="",
                        github_username="",
                        github_access_token="",
                        updated_at=now,
                    )
                    records[index] = updated
                    self._save(records)
                    return updated
        return None

    def scrub_underage(self, user_id: str) -> bool:
        """Delete a just-created under-13 account (age-gate block)."""
        with self._lock:
            records = self._load()
            kept = [u for u in records if u.id != user_id]
            if len(kept) == len(records):
                return False
            self._save(kept)
            return True

    def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user record (admin action)."""
        with self._lock:
            records = self._load()
            kept = [u for u in records if u.id != user_id]
            if len(kept) == len(records):
                return False
            self._save(kept)
            return True

    # -- email/password auth: not supported by the JSON store ---------

    def _email_unsupported(self) -> None:
        raise RuntimeError("Email/password auth requires the SQL user store.")

    def get_by_email(self, email: str) -> OAuthUser | None:
        self._email_unsupported()
        return None

    def create_email_user(
        self, email: str, name: str, password_hash: str
    ) -> OAuthUser:
        self._email_unsupported()
        raise RuntimeError("unreachable")

    def get_password_hash(self, user_id: str) -> str | None:
        self._email_unsupported()
        return None

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        self._email_unsupported()

    def is_email_verified(self, user_id: str) -> bool:
        self._email_unsupported()
        return False

    def set_email_verified(self, user_id: str, verified: bool = True) -> None:
        self._email_unsupported()

    def set_email_verify_token(
        self, user_id: str, token_hash: str | None
    ) -> None:
        self._email_unsupported()

    def get_by_verify_token(self, token_hash: str) -> OAuthUser | None:
        self._email_unsupported()
        return None

    def set_password_reset_token(
        self, user_id: str, token_hash: str | None, expires_at: str | None
    ) -> None:
        self._email_unsupported()

    def get_by_reset_token(self, token_hash: str) -> OAuthUser | None:
        self._email_unsupported()
        return None


_user_store: UserStore = OAuthUserStore()


def get_oauth_user_store() -> UserStore:
    return _user_store


def set_oauth_user_store(store: UserStore) -> None:
    """Replace the process-wide OAuth user store.

    Used by tests, and by persistence startup to swap in the
    database-backed ``SqlUserStore`` when SQL is configured.
    """
    global _user_store
    _user_store = store


def _github_redirect_uri(config: OAuthConfig) -> str:
    return f"{config.public_url}/api/auth/github/callback"


def _google_redirect_uri(config: OAuthConfig) -> str:
    return f"{config.public_url}/api/auth/google/callback"


@router.get("/github/login")
async def github_login() -> RedirectResponse:
    config = oauth_config()
    if not config.github_client_id:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth is not configured: set GITHUB_OAUTH_CLIENT_ID",
        )
    params = urlencode(
        {
            "client_id": config.github_client_id,
            "redirect_uri": _github_redirect_uri(config),
            "state": new_state(config.session_secret),
            "scope": "read:user repo",
        }
    )
    return RedirectResponse(url=f"{_GITHUB_AUTHORIZE_URL}?{params}", status_code=302)


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    config = oauth_config()
    if not config.google_client_id:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured: set GOOGLE_OAUTH_CLIENT_ID",
        )
    params = urlencode(
        {
            "client_id": config.google_client_id,
            "redirect_uri": _google_redirect_uri(config),
            "response_type": "code",
            "scope": "openid email profile",
            "state": new_state(config.session_secret),
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(url=f"{_GOOGLE_AUTHORIZE_URL}?{params}", status_code=302)


def _exchange_error_detail(
    provider: str, status: int, payload: dict[str, Any]
) -> str:
    """Build an honest token-exchange failure detail from the provider's body.

    OAuth token endpoints return ``error`` / ``error_description`` on failure
    (RFC 6749 §5.2); surfacing them ends blind debugging loops. The client
    secret is never logged or returned here.
    """
    base = f"{provider} token exchange failed"
    error = str(payload.get("error") or "")[:80]
    description = str(payload.get("error_description") or "")[:200]
    if not error and not description:
        return base
    logger.warning(
        "%s token exchange failed: http_status=%s error=%r description=%r",
        provider,
        status,
        error,
        description,
    )
    detail = f"{base}: {error}" if error else base
    if description:
        detail = f"{detail} ({description})"
    return detail


def _exchange_github_code(config: OAuthConfig, code: str) -> str:
    status, payload = _http_post(
        _GITHUB_TOKEN_URL,
        {
            "client_id": config.github_client_id,
            "client_secret": config.github_client_secret,
            "code": code,
            "redirect_uri": _github_redirect_uri(config),
        },
        {"Accept": "application/json"},
    )
    token = str(payload.get("access_token", ""))
    if status != 200 or not token:
        raise HTTPException(
            status_code=502, detail=_exchange_error_detail("GitHub", status, payload)
        )
    return token


def _github_profile(token: str) -> dict[str, Any]:
    status, payload = _http_get(
        _GITHUB_USER_URL,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        },
    )
    if status != 200 or "id" not in payload:
        raise HTTPException(status_code=502, detail="GitHub profile fetch failed")
    return payload


def _exchange_google_code(config: OAuthConfig, code: str) -> str:
    status, payload = _http_post(
        _GOOGLE_TOKEN_URL,
        {
            "code": code,
            "client_id": config.google_client_id,
            "client_secret": config.google_client_secret,
            "redirect_uri": _google_redirect_uri(config),
            "grant_type": "authorization_code",
        },
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = str(payload.get("access_token", ""))
    if status != 200 or not token:
        raise HTTPException(
            status_code=502, detail=_exchange_error_detail("Google", status, payload)
        )
    return token


def _google_profile(token: str) -> dict[str, Any]:
    status, payload = _http_get(
        _GOOGLE_USERINFO_URL,
        {"Authorization": f"Bearer {token}"},
    )
    if status != 200 or "sub" not in payload:
        raise HTTPException(status_code=502, detail="Google profile fetch failed")
    return payload


_REFRESH_COOKIE = "sonar_refresh"


def _set_session_cookie(
    response: Response,
    user_id: str,
    secret: str,
    request: Request | None = None,
) -> None:
    """Issue a server-side session: short-lived access token + refresh cookie.

    Falls back to the legacy stateless JWT when the session store is
    unavailable, so login never breaks.
    """
    from app.sessions.sessions import (
        get_session_store,
        hash_refresh_token,
        new_access_token,
        new_refresh_token,
    )

    ip, user_agent = _client_info(request)
    device_info = (user_agent or "")[:512]
    try:
        store = get_session_store()
        refresh_token = new_refresh_token()
        session = store.create(
            user_id,
            hash_refresh_token(refresh_token),
            device_info=device_info,
            ip_address=ip,
        )
        access_token = new_access_token(session.session_id, user_id, secret)
        # Refresh cookie carries "session_id.refresh_token" so rotation can
        # find the session without scanning hashes.
        refresh_value = f"{session.session_id}.{refresh_token}"
    except Exception:
        access_token = new_session_token(user_id, secret)
        refresh_value = None
    response.set_cookie(
        _SESSION_COOKIE,
        access_token,
        max_age=15 * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    if refresh_value is not None:
        response.set_cookie(
            _REFRESH_COOKIE,
            refresh_value,
            max_age=30 * 24 * 60 * 60,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/api/auth/refresh",
        )


def _client_info(request: Request | None) -> tuple[str | None, str | None]:
    """(ip_address, user_agent) for security event logging."""
    if request is None:
        return None, None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        ip = None
    return ip, request.headers.get("user-agent")


def _login_response(
    user_id: str, secret: str, request: Request | None = None, provider: str = "oauth"
) -> RedirectResponse:
    """Post-OAuth login response: 2FA challenge when enrolled, else session.

    When the user has TOTP enabled, no session cookie is issued yet.
    Instead a short-lived pending token goes in a cookie and the browser
    is sent to /2fa/verify to complete the second factor.
    """
    from app.twofa.api import _PENDING_COOKIE, new_pending_token
    from app.twofa.store import get_two_factor_store

    record = get_two_factor_store().get(user_id)
    ip, user_agent = _client_info(request)
    if record is not None and record.enabled:
        response = RedirectResponse(url="/2fa/verify", status_code=302)
        response.set_cookie(
            _PENDING_COOKIE,
            new_pending_token(user_id),
            max_age=5 * 60,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return response
    from app.security_events.events import log_login_success

    log_login_success(user_id, ip_address=ip, user_agent=user_agent, provider=provider)
    response = RedirectResponse(url="/app", status_code=302)
    _set_session_cookie(response, user_id, secret, request)
    return response


def _github_upsert_fields(profile: dict[str, Any], token: str) -> dict[str, Any]:
    """Map a GitHub profile payload to ``OAuthUserStore.upsert()`` kwargs."""
    return {
        "provider": "github",
        "provider_user_id": str(profile["id"]),
        "name": str(profile.get("name") or profile.get("login") or ""),
        "email": str(profile.get("email") or ""),
        "avatar_url": str(profile.get("avatar_url") or ""),
        "github_access_token": token,
        "github_username": str(profile.get("login") or ""),
    }


def _owner_email() -> str:
    """Normalized owner email for the one-time admin bootstrap (empty when unset)."""
    return os.environ.get("CODESONAR_OWNER_EMAIL", "").strip().lower()


def _store_has_admin(store: Any) -> bool:
    """True when any admin already exists in the user store."""
    if hasattr(store, "list_users"):
        users = store.list_users(limit=500, offset=0)
    elif hasattr(store, "load_all"):
        users = list(store.load_all())
    else:
        return False
    return any(getattr(u, "is_admin", False) for u in users)


def _grant_owner_flags(store: Any, user_id: str) -> None:
    """Grant admin + staff through whichever setters the store provides."""
    for kind in ("admin", "staff"):
        setter = getattr(store, f"set_{kind}", None)
        if setter is not None:
            setter(user_id, True)


def _maybe_bootstrap_owner(user: OAuthUser) -> OAuthUser:
    """One-time owner bootstrap: first login matching CODESONAR_OWNER_EMAIL.

    When the env var is set and the logging-in user's email matches it
    (case-insensitive), and no admin exists yet in the user store, that
    user is granted admin + staff. This seeds the first admin without
    touching the database by hand, and becomes a no-op afterwards.
    """
    if not _owner_email() or (user.email or "").strip().lower() != _owner_email():
        return user
    if user.is_admin and user.is_staff:
        return user
    store = get_oauth_user_store()
    try:
        if _store_has_admin(store):
            return user
        _grant_owner_flags(store, user.id)
        logger.warning("Owner bootstrap: granted admin+staff to %s", user.id)
        return store.get(user.id) or user
    except Exception:
        logger.exception("Owner bootstrap failed for %s", user.id)
        return user


@router.get("/github/connect")
async def github_connect(request: Request) -> RedirectResponse:
    """Start GitHub account linking for the signed-in user.

    Unlike ``/github/login`` (which mints a brand-new session), this attaches
    the GitHub OAuth token to the caller's existing account so repo listing
    and private-repo clones work without switching logins.
    """
    user = require_user(request)
    config = oauth_config()
    if not config.github_client_id:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth is not configured: set GITHUB_OAUTH_CLIENT_ID",
        )
    params = urlencode(
        {
            "client_id": config.github_client_id,
            "redirect_uri": _github_redirect_uri(config),
            "state": new_github_connect_state(config.session_secret, user.id),
            "scope": "read:user repo",
        }
    )
    return RedirectResponse(url=f"{_GITHUB_AUTHORIZE_URL}?{params}", status_code=302)


@router.post("/github/disconnect")
async def github_disconnect(request: Request) -> dict[str, Any]:
    """Remove the linked GitHub account from the signed-in user."""
    user = require_user(request)
    updated = get_oauth_user_store().unlink_github(user.id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "disconnected"}


@router.get("/github/callback")
async def github_callback(
    request: Request, code: str | None = None, state: str | None = None
) -> RedirectResponse:
    config = oauth_config()
    if not config.github_client_id or not config.github_client_secret:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")
    if not verify_state(state, config.session_secret):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    token = _exchange_github_code(config, code)
    profile = _github_profile(token)

    connect_user_id = parse_github_connect_state(state, config.session_secret)
    if connect_user_id is not None:
        # Account-linking flow: attach the token to the signed-in account.
        # Never mints a session, never changes plan/flags, never bootstraps.
        user = require_user(request)
        if user.id != connect_user_id:
            raise HTTPException(status_code=403, detail="OAuth session mismatch")
        store = get_oauth_user_store()
        github_id = str(profile["id"])
        owner = store.get_by_github_id(github_id)
        if owner is not None and owner.id != user.id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This GitHub account is already linked to a different "
                    "Code Sonar account. Sign in with GitHub to use that "
                    "account, or disconnect GitHub there first."
                ),
            )
        try:
            updated = store.link_github(
                user.id,
                github_id=github_id,
                github_username=str(profile.get("login") or ""),
                github_access_token=token,
            )
        except GitHubIdentityConflictError:
            # Lost a race between the pre-check and the write (or a store
            # that enforces uniqueness itself): same honest outcome, no 500.
            raise HTTPException(
                status_code=409,
                detail=(
                    "This GitHub account is already linked to a different "
                    "Code Sonar account. Sign in with GitHub to use that "
                    "account, or disconnect GitHub there first."
                ),
            )
        if updated is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return RedirectResponse(url="/app", status_code=302)

    user = get_oauth_user_store().upsert(**_github_upsert_fields(profile, token))
    user = _maybe_bootstrap_owner(user)
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account is suspended")
    return _login_response(user.id, config.session_secret, request, provider="github")


@router.get("/google/callback")
async def google_callback(
    request: Request, code: str | None = None, state: str | None = None
) -> RedirectResponse:
    config = oauth_config()
    if not config.google_client_id or not config.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")
    if not verify_state(state, config.session_secret):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    token = _exchange_google_code(config, code)
    profile = _google_profile(token)
    user = get_oauth_user_store().upsert(
        provider="google",
        provider_user_id=str(profile["sub"]),
        name=str(profile.get("name") or ""),
        email=str(profile.get("email") or ""),
        avatar_url=str(profile.get("picture") or ""),
    )
    user = _maybe_bootstrap_owner(user)
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account is suspended")
    return _login_response(user.id, config.session_secret, request, provider="google")


def current_user(request: Request) -> OAuthUser | None:
    """Resolve the signed session cookie to a user, or None when absent.

    Suspended users resolve to None: their sessions are dead. Revoked
    server-side sessions resolve to None as well. Legacy stateless JWTs
    (no ``sid`` claim) keep working until they expire.
    """
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    user_id = verify_session_token(token, _session_secret())
    if not user_id:
        return None
    # Server-side session check: a revoked session kills the access token.
    try:
        from app.sessions.sessions import decode_access_token, get_session_store

        payload = decode_access_token(token, _session_secret())
        session_id = (payload or {}).get("sid")
        if session_id:
            session = get_session_store().get(str(session_id))
            if session is None or session.revoked:
                return None
            if session.user_id != user_id:
                return None
    except Exception:
        pass
    user = get_oauth_user_store().get(user_id)
    if user is None or user.is_suspended:
        return None
    return user


def current_session_id(request: Request) -> str | None:
    """The server-side session id for this request, if it has one."""
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    try:
        from app.sessions.sessions import decode_access_token

        payload = decode_access_token(token, _session_secret())
        session_id = (payload or {}).get("sid")
        return str(session_id) if session_id else None
    except Exception:
        return None


def require_user(request: Request) -> OAuthUser:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


@router.get("/me")
async def auth_me(request: Request) -> dict[str, Any]:
    user = require_user(request)
    # The public projection hides account internals; the signed-in user
    # additionally sees their own plan and privilege flags so the UI can
    # gate the admin console. Other users' flags stay admin-only.
    return {
        **user.public_dict(),
        "plan": user.plan,
        "is_admin": bool(getattr(user, "is_admin", False)),
        "is_staff": bool(getattr(user, "is_staff", False)),
    }


@router.post("/logout")
async def auth_logout(request: Request) -> JSONResponse:
    from app.security_events.events import LOGOUT, log_event
    from app.sessions.sessions import get_session_store

    session_id = current_session_id(request)
    token = request.cookies.get(_SESSION_COOKIE)
    user_id = verify_session_token(token, _session_secret()) if token else None
    if session_id:
        try:
            get_session_store().revoke(session_id)
        except Exception:
            pass
    if user_id:
        log_event(LOGOUT, user_id=user_id)
    response = JSONResponse(content={"status": "signed_out"})
    response.delete_cookie(_SESSION_COOKIE, path="/")
    response.delete_cookie(_REFRESH_COOKIE, path="/api/auth/refresh")
    return response


@router.get("/repos")
async def auth_repos(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not user.github_access_token:
        raise HTTPException(
            status_code=409,
            detail="No GitHub account is connected; sign in with GitHub first",
        )
    status, payload = _http_get(
        f"{_GITHUB_REPOS_URL}?per_page=100&sort=pushed",
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {user.github_access_token}",
        },
    )
    if status != 200:
        raise HTTPException(status_code=502, detail="GitHub repository fetch failed")
    items = payload.get("_items", [])
    repos = [
        {
            "id": item.get("id"),
            "full_name": item.get("full_name"),
            "name": item.get("name"),
            "pushed_at": item.get("pushed_at"),
            "private": item.get("private"),
            "default_branch": item.get("default_branch"),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return {"count": len(repos), "repos": repos}
