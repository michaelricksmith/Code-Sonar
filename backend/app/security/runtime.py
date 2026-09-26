"""Process-boundary security controls for the HTTP API."""

from __future__ import annotations

import hmac
import json
import os
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.oauth import current_user, session_secret_configured
from app.security.tenant import LOCAL_TENANT_ID, bind_tenant, reset_tenant

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# OAuth handshake endpoints must be reachable without authentication so a
# signed-out user can START sign-in. Everything else under /api/ requires a
# valid Bearer token or a valid signed session cookie.
PUBLIC_AUTH_PATHS = frozenset(
    {
        "/api/auth/github/login",
        "/api/auth/google/login",
        "/api/auth/github/callback",
        "/api/auth/google/callback",
        # Temporary one-time wipe endpoint (app/admin_wipe.py): guarded by its
        # own WIPE_TOKEN; removed immediately after the wipe is verified.
        "/api/admin/wipe-user-data",
    }
)
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
WEBHOOK_PATH = "/api/github-app/webhook"


def local_dev_enabled() -> bool:
    return os.environ.get("CODESONAR_LOCAL_DEV", "0") == "1"


def configured_origins() -> tuple[str, ...]:
    raw = os.environ.get("CODESONAR_CORS_ORIGINS")
    origins = DEFAULT_CORS_ORIGINS if raw is None else tuple(
        item.strip().rstrip("/") for item in raw.split(",") if item.strip()
    )
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise RuntimeError(f"Invalid CODESONAR_CORS_ORIGINS entry: {origin!r}")
    return origins


def validate_runtime_security_config() -> None:
    host = os.environ.get("CODESONAR_HOST", "127.0.0.1").strip().lower()
    credentials = configured_tenant_credentials()
    if (
        not credentials
        and not session_secret_configured()
        and (not local_dev_enabled() or host not in LOCAL_HOSTS)
    ):
        raise RuntimeError(
            "CODESONAR_API_TOKEN is required unless SONAR_SESSION_SECRET is set "
            "(OAuth session-cookie auth) or CODESONAR_LOCAL_DEV=1 and "
            "CODESONAR_HOST is loopback"
        )
    configured_origins()


def configured_tenant_credentials() -> dict[str, str]:
    """Load server-owned tenant-to-token bindings.

    ``CODESONAR_API_TENANT_TOKENS`` is a JSON object. The legacy single token
    remains supported and is bound to ``CODESONAR_TENANT_ID`` (``local`` by
    default). Caller-supplied tenant headers are intentionally ignored.
    """
    bindings: dict[str, str] = {}
    raw = os.environ.get("CODESONAR_API_TENANT_TOKENS", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("CODESONAR_API_TENANT_TOKENS must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("CODESONAR_API_TENANT_TOKENS must be a JSON object")
        for tenant_id, credential in parsed.items():
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                raise RuntimeError("Tenant identifiers must be non-empty strings")
            if not isinstance(credential, str) or not credential.strip():
                raise RuntimeError("Tenant API tokens must be non-empty strings")
            bindings[tenant_id.strip()] = credential.strip()
    legacy = os.environ.get("CODESONAR_API_TOKEN", "").strip()
    if legacy:
        tenant_id = os.environ.get("CODESONAR_TENANT_ID", LOCAL_TENANT_ID).strip()
        if not tenant_id:
            raise RuntimeError("CODESONAR_TENANT_ID must be non-empty")
        if tenant_id in bindings and bindings[tenant_id] != legacy:
            raise RuntimeError("Conflicting API tokens configured for the same tenant")
        bindings[tenant_id] = legacy
    tokens = list(bindings.values())
    if len(tokens) != len(set(tokens)):
        raise RuntimeError("Tenant API tokens must be unique")
    return bindings


def _authenticate_tenant(authorization: str) -> str | None:
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        return None
    for tenant_id, expected in configured_tenant_credentials().items():
        if hmac.compare_digest(credential, expected):
            return tenant_id
    return None


class ApiBoundaryMiddleware(BaseHTTPMiddleware):
    """Enforce authentication and an exact CORS origin allowlist.

    Authentication is satisfied by EITHER a valid Bearer token (server-owned
    tenant credential) OR a valid signed ``sonar_session`` cookie (OAuth
    sign-in). No dev flag is required for hosted operation; the OAuth
    handshake paths stay public so sign-in can start.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        allowed_origins = configured_origins()
        if origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)

        if (
            request.method != "OPTIONS"
            and request.url.path.startswith("/api/")
            and request.url.path != WEBHOOK_PATH
            and request.url.path not in PUBLIC_AUTH_PATHS
        ):
            credentials = configured_tenant_credentials()
            tenant_id = _authenticate_tenant(request.headers.get("authorization", ""))
            session_user = current_user(request) if tenant_id is None else None
            if tenant_id is None and session_user is None:
                # Local dev without any configured credential keeps its
                # unauthenticated ergonomics; every other deployment fails closed.
                if credentials or not local_dev_enabled():
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)

            # Session-cookie users share the local tenant, matching the
            # single-tenant dashboard posture.
            tenant_token = bind_tenant(tenant_id or LOCAL_TENANT_ID)
        else:
            tenant_token = bind_tenant(LOCAL_TENANT_ID)

        try:
            if request.method == "OPTIONS" and origin:
                response: Response = Response(status_code=204)
            else:
                response = await call_next(request)
        finally:
            reset_tenant(tenant_token)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin.rstrip("/")
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-GitHub-Event, "
                "X-GitHub-Delivery, X-Hub-Signature-256"
            )
        return response
