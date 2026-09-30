"""In-memory sliding-window rate limiting for expensive endpoints.

The backend previously had no rate limiting at all: monthly billing quotas
don't stop a caller from firing thousands of paid LLM calls (Ask Sonar) or
clone+rewrite+rescan pipelines (remediation) in minutes. This module adds
short-window per-caller limits that 429 before the expensive work starts.

Limits are keyed on the signed-in user id when available, otherwise on the
client IP (honoring ``X-Forwarded-For`` behind the Render proxy).
"""

from __future__ import annotations

import functools
import threading
import time
from collections import deque
from typing import Any, Callable

from fastapi import HTTPException, Request

_WINDOW_BUCKETS: dict[str, deque[float]] = {}
_LOCK = threading.Lock()
_MAX_KEYS = 50_000


def _caller_key(request: Request) -> str:
    # Deferred: app.oauth pulls in app.main-adjacent modules at import time.
    try:
        from app.oauth import current_user

        user = current_user(request)
    except Exception:
        user = None
    if user is not None:
        return f"user:{user.id}"
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else ""
    if not ip and request.client is not None:
        ip = request.client.host or ""
    return f"ip:{ip or 'unknown'}"


def check_rate_limit(request: Request, limit: int, window_seconds: int) -> None:
    """Raise 429 when ``request``'s caller exceeded ``limit``/``window_seconds``."""
    key = f"{limit}/{window_seconds}:{_caller_key(request)}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _WINDOW_BUCKETS.get(key)
        if bucket is None:
            bucket = _WINDOW_BUCKETS[key] = deque()
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = int(bucket[0] + window_seconds - now) + 1
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limited",
                    "message": "Too many requests — please slow down and try again shortly.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
        if len(_WINDOW_BUCKETS) > _MAX_KEYS:
            # Bound memory: drop the oldest quarter of keys.
            for old_key in list(_WINDOW_BUCKETS)[: _MAX_KEYS // 4]:
                _WINDOW_BUCKETS.pop(old_key, None)


def reset_rate_limits() -> None:
    """Clear all buckets. Used by tests."""
    with _LOCK:
        _WINDOW_BUCKETS.clear()


def rate_limit(limit: int, window_seconds: int) -> Callable:
    """Endpoint decorator applying :func:`check_rate_limit` first."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = None
            for candidate in list(kwargs.values()) + list(args):
                if isinstance(candidate, Request):
                    request = candidate
                    break
            if request is not None:
                check_rate_limit(request, limit, window_seconds)
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
