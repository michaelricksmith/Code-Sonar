"""Process-boundary security controls for the HTTP API."""

from __future__ import annotations

import hmac
import os
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
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
    token = os.environ.get("CODESONAR_API_TOKEN", "").strip()
    if not token and (not local_dev_enabled() or host not in LOCAL_HOSTS):
        raise RuntimeError(
            "CODESONAR_API_TOKEN is required unless CODESONAR_LOCAL_DEV=1 "
            "and CODESONAR_HOST is loopback"
        )
    configured_origins()


class ApiBoundaryMiddleware(BaseHTTPMiddleware):
    """Enforce bearer authentication and an exact CORS origin allowlist."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        allowed_origins = configured_origins()
        if origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)

        if (
            request.method != "OPTIONS"
            and request.url.path.startswith("/api/")
            and request.url.path != WEBHOOK_PATH
        ):
            token = os.environ.get("CODESONAR_API_TOKEN", "").strip()
            if token:
                scheme, _, credential = request.headers.get("authorization", "").partition(" ")
                if scheme.lower() != "bearer" or not hmac.compare_digest(credential, token):
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            elif not local_dev_enabled():
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        if request.method == "OPTIONS" and origin:
            response: Response = Response(status_code=204)
        else:
            response = await call_next(request)
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
