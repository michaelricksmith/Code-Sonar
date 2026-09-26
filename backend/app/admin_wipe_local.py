"""Temporary one-time local user-data wipe endpoint.

Added 2026-09-25 at the owner's explicit request ("clear all the user data...
fresh start"). The earlier SQL-only wipe (PRs #60/#61) cleared the database
tables, but the dashboard kept showing the old data because the product's
dashboard reads from JSON/JSONL files under ~/.code-sonar on the instance's
local disk (projects.json, history.jsonl, remediation-outcomes.jsonl, ...),
not from the SQL tables. This endpoint deletes those local user-data files.

Kept: oauth-users.json (sign-in must keep working). Removed immediately
after the wipe is verified — it is not a product feature.

Guarded by the WIPE_TOKEN environment variable (constant-time compare);
without it the route behaves as if it does not exist.
"""

from __future__ import annotations

import hmac
import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Local user-data files/dirs under the data root. oauth-users.json is
# deliberately absent: wiping it would break sign-in.
_WIPE_PATHS = (
    "history.jsonl",
    "projects.json",
    "github-installations.json",
    "github-webhooks.jsonl",
    "github-webhook-jobs.json",
    "remediation-outcomes.jsonl",
    "repositories",
)

_SQL_TABLES = (
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


def _data_root() -> Path:
    return Path(os.environ.get("CODESONAR_HOME", str(Path.home()))) / ".code-sonar"


def _authorized(request: Request) -> bool:
    expected = os.environ.get("WIPE_TOKEN")
    if not expected:
        return False
    provided = request.headers.get("x-wipe-token", "")
    return hmac.compare_digest(provided, expected)


@router.post("/wipe-local-data")
async def wipe_local_data(request: Request) -> JSONResponse:
    if not _authorized(request):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    root = _data_root()
    files: dict[str, Any] = {}
    for name in _WIPE_PATHS:
        target = root / name
        existed = target.exists()
        deleted = False
        if existed:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            deleted = True
        files[name] = {
            "existed": existed,
            "deleted": deleted,
            "exists_after": target.exists(),
        }
    sql_after: dict[str, Any] = {}
    try:
        from app.persistence.runtime import get_persistence

        persistence = get_persistence()
        if persistence is not None:
            with persistence.engine.begin() as connection:
                for table in _SQL_TABLES:
                    sql_after[table] = connection.execute(
                        text(f"SELECT count(*) FROM {table}")
                    ).scalar()
    except Exception as exc:  # noqa: BLE001 - report, don't fail the wipe
        sql_after["error"] = str(exc)
    wiped = all(not info["exists_after"] for info in files.values()) and all(
        v == 0 for v in sql_after.values() if isinstance(v, int)
    )
    return JSONResponse(
        status_code=200, content={"files": files, "sql_after": sql_after, "wiped": wiped}
    )
