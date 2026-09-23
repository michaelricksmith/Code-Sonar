"""GitHub + Google OAuth Authorization Code flow for Code Sonar users.

Config comes only from the environment (never hardcoded, never logged):

- GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET
- GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET
- SONAR_PUBLIC_URL (used to build redirect URIs)
- SONAR_SESSION_SECRET (dev fallback is a random per-process secret with a
  loud startup warning)

OAuth access tokens are stored server-side only (JSON user store under
~/.code-sonar/, mode 0600) and are never returned to any client.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

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


def _default_http_get(
    url: str, headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
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


def set_oauth_transport(
    http_post: HttpPost | None = None, http_get: HttpGet | None = None
) -> None:
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


def _session_secret() -> str:
    global _secret_warning_emitted
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
    return secrets.token_hex(32)


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

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "provider": self.provider,
        }


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

    def upsert(
        self,
        *,
        provider: str,
        provider_user_id: str,
        name: str,
        email: str,
        avatar_url: str,
        github_access_token: str = "",
    ) -> OAuthUser:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            records = self._load()
            for index, existing in enumerate(records):
                if (
                    existing.provider == provider
                    and existing.provider_user_id == provider_user_id
                ):
                    updated = OAuthUser(
                        id=existing.id,
                        provider=provider,
                        provider_user_id=provider_user_id,
                        name=name or existing.name,
                        email=email or existing.email,
                        avatar_url=avatar_url or existing.avatar_url,
                        github_access_token=github_access_token
                        or existing.github_access_token,
                        created_at=existing.created_at,
                        updated_at=now,
                    )
                    records[index] = updated
                    self._save(records)
                    return updated
            user = OAuthUser(
                id=uuid.uuid4().hex,
                provider=provider,
                provider_user_id=provider_user_id,
                name=name,
                email=email,
                avatar_url=avatar_url,
                github_access_token=github_access_token,
                created_at=now,
                updated_at=now,
            )
            records.append(user)
            self._save(records)
            return user


_user_store = OAuthUserStore()


def get_oauth_user_store() -> OAuthUserStore:
    return _user_store


def set_oauth_user_store(store: OAuthUserStore) -> None:
    """Replace the process-wide OAuth user store. Used by tests."""
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
        raise HTTPException(status_code=502, detail="GitHub token exchange failed")
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
        raise HTTPException(status_code=502, detail="Google token exchange failed")
    return token


def _google_profile(token: str) -> dict[str, Any]:
    status, payload = _http_get(
        _GOOGLE_USERINFO_URL,
        {"Authorization": f"Bearer {token}"},
    )
    if status != 200 or "sub" not in payload:
        raise HTTPException(status_code=502, detail="Google profile fetch failed")
    return payload


def _set_session_cookie(response: RedirectResponse, user_id: str, secret: str) -> None:
    response.set_cookie(
        _SESSION_COOKIE,
        new_session_token(user_id, secret),
        max_age=_SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.get("/github/callback")
async def github_callback(code: str | None = None, state: str | None = None) -> RedirectResponse:
    config = oauth_config()
    if not config.github_client_id or not config.github_client_secret:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")
    if not verify_state(state, config.session_secret):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    token = _exchange_github_code(config, code)
    profile = _github_profile(token)
    user = get_oauth_user_store().upsert(
        provider="github",
        provider_user_id=str(profile["id"]),
        name=str(profile.get("name") or profile.get("login") or ""),
        email=str(profile.get("email") or ""),
        avatar_url=str(profile.get("avatar_url") or ""),
        github_access_token=token,
    )
    response = RedirectResponse(url="/app", status_code=302)
    _set_session_cookie(response, user.id, config.session_secret)
    return response


@router.get("/google/callback")
async def google_callback(code: str | None = None, state: str | None = None) -> RedirectResponse:
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
    response = RedirectResponse(url="/app", status_code=302)
    _set_session_cookie(response, user.id, config.session_secret)
    return response


def current_user(request: Request) -> OAuthUser | None:
    """Resolve the signed session cookie to a user, or None when absent."""
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    user_id = verify_session_token(token, _session_secret())
    if not user_id:
        return None
    return get_oauth_user_store().get(user_id)


def require_user(request: Request) -> OAuthUser:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


@router.get("/me")
async def auth_me(request: Request) -> dict[str, Any]:
    return require_user(request).public_dict()


@router.post("/logout")
async def auth_logout() -> JSONResponse:
    response = JSONResponse(content={"status": "signed_out"})
    response.delete_cookie(_SESSION_COOKIE, path="/")
    return response


@router.get("/repos")
async def auth_repos(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if user.provider != "github" or not user.github_access_token:
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
