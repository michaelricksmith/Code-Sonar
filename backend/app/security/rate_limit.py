"""Sliding-window rate limiting for expensive endpoints.

The backend previously had no rate limiting at all: monthly billing quotas
don't stop a caller from firing thousands of paid LLM calls (Ask Sonar) or
clone+rewrite+rescan pipelines (remediation) in minutes. This module adds
short-window per-caller limits that 429 before the expensive work starts.

Limits are keyed on the signed-in user id when available, otherwise on the
client IP (honoring ``X-Forwarded-For`` behind the Render proxy).

Buckets are shared across workers via the ``rate_limit_hits`` SQL table
whenever SQL persistence is configured (``CODESONAR_DATABASE_URL``). When the
database is unavailable (local dev, or a DB outage) the limiter falls back
to process-local memory — a per-process limit beats a 500 on every request.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

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


def _rate_limit_exceeded(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "rate_limited",
            "message": "Too many requests — please slow down and try again shortly.",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


def _check_memory(bucket_key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _WINDOW_BUCKETS.get(bucket_key)
        if bucket is None:
            bucket = _WINDOW_BUCKETS[bucket_key] = deque()
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = int(bucket[0] + window_seconds - now) + 1
            raise _rate_limit_exceeded(retry_after)
        bucket.append(now)
        if len(_WINDOW_BUCKETS) > _MAX_KEYS:
            # Bound memory: drop the oldest quarter of keys.
            for old_key in list(_WINDOW_BUCKETS)[: _MAX_KEYS // 4]:
                _WINDOW_BUCKETS.pop(old_key, None)


def _sql_engine() -> Any | None:
    # Deferred import: the persistence runtime pulls in half the app.
    try:
        from app.persistence.runtime import get_persistence

        persistence = get_persistence()
        return persistence.engine if persistence is not None else None
    except Exception:
        return None


def _check_sql(engine: Any, bucket_key: str, limit: int, window_seconds: int) -> None:
    """Sliding window in the shared ``rate_limit_hits`` table.

    On PostgreSQL a transaction-scoped advisory lock serializes concurrent
    checks for the same bucket, so two workers racing at the boundary cannot
    both count ``N < limit`` and both insert. On other dialects (SQLite in
    tests / local dev) writers serialize on the database lock instead. The
    fail direction is always closed: a lost race rejects, never over-admits.
    """
    from sqlalchemy import delete, func, insert, select, text

    from app.persistence.schema import rate_limit_hits

    now = time.time()
    cutoff = now - window_seconds
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:bucket_key))"),
                {"bucket_key": bucket_key},
            )
        connection.execute(
            delete(rate_limit_hits).where(
                rate_limit_hits.c.bucket_key == bucket_key,
                rate_limit_hits.c.hit_at <= cutoff,
            )
        )
        count = connection.execute(
            select(func.count())
            .select_from(rate_limit_hits)
            .where(rate_limit_hits.c.bucket_key == bucket_key)
        ).scalar()
        if count is not None and count >= limit:
            oldest = connection.execute(
                select(rate_limit_hits.c.hit_at)
                .where(rate_limit_hits.c.bucket_key == bucket_key)
                .order_by(rate_limit_hits.c.hit_at)
                .limit(1)
            ).scalar()
            retry_after = (
                int(oldest + window_seconds - now) + 1 if oldest is not None else window_seconds
            )
            raise _rate_limit_exceeded(retry_after)
        connection.execute(insert(rate_limit_hits).values(bucket_key=bucket_key, hit_at=now))


def check_rate_limit(request: Request, limit: int, window_seconds: int) -> None:
    """Raise 429 when ``request``'s caller exceeded ``limit``/``window_seconds``."""
    key = f"{limit}/{window_seconds}:{_caller_key(request)}"
    engine = _sql_engine()
    if engine is not None:
        try:
            _check_sql(engine, key, limit, window_seconds)
            return
        except HTTPException:
            raise
        except Exception as exc:
            # A DB outage must not 500 every request: degrade to the
            # process-local limiter and keep serving.
            logger.warning("SQL rate-limit check failed; using memory fallback: %s", exc)
    _check_memory(key, limit, window_seconds)


def reset_rate_limits() -> None:
    """Clear all buckets. Used by tests."""
    with _LOCK:
        _WINDOW_BUCKETS.clear()


def rate_limit(limit: int, window_seconds: int) -> Callable[..., Callable[..., Any]]:
    """Endpoint decorator applying :func:`check_rate_limit` first."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
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
