"""Temporary one-time user-data wipe endpoint.

Added 2026-09-25 at the owner's explicit request ("clear all the user data...
fresh start"). Render's free plan has no shell/SSH access, so the wipe could
not be run from the dashboard; this endpoint performs it instead. It is
removed immediately after the wipe is verified — it is not a product feature
(the product's deletion path remains the privacy API's deletion-request flow).

Guarded by the WIPE_TOKEN environment variable (compared in constant time);
without it the route behaves as if it does not exist.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/api/admin", tags=["admin"])

_WIPE_TABLES = (
    "remediation_outcomes",
    "findings",
    "webhook_jobs",
    "webhook_deliveries",
    "github_installations",
    "privacy_audit_events",
    "privacy_jobs",
    "migration_ledger",
    "scans",
    "projects",
)


def _authorized(request: Request) -> bool:
    expected = os.environ.get("WIPE_TOKEN")
    if not expected:
        return False
    provided = request.headers.get("x-wipe-token", "")
    return hmac.compare_digest(provided, expected)


@router.post("/wipe-user-data")
async def wipe_user_data(request: Request) -> JSONResponse:
    if not _authorized(request):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    from app.persistence.runtime import get_persistence

    persistence = get_persistence()
    if persistence is None:
        return JSONResponse(status_code=503, content={"detail": "Persistence unavailable"})
    counts: dict[str, Any] = {"before": {}, "deleted": {}, "after": {}}
    with persistence.engine.begin() as connection:
        for table in _WIPE_TABLES:
            counts["before"][table] = connection.execute(
                text(f"SELECT count(*) FROM {table}")
            ).scalar()
        for table in _WIPE_TABLES:
            counts["deleted"][table] = connection.execute(
                text(f"DELETE FROM {table}")
            ).rowcount
        for table in _WIPE_TABLES:
            counts["after"][table] = connection.execute(
                text(f"SELECT count(*) FROM {table}")
            ).scalar()
    counts["wiped"] = all(v == 0 for v in counts["after"].values())
    return JSONResponse(status_code=200, content=counts)
