"""Per-scan ownership enforcement (cross-tenant IDOR fix).

Session-cookie users share the ``"local"`` tenant, so the tenant check alone
cannot tell users apart: any signed-in user could previously read, query, and
run remediation against any other user's scan. Scan records now carry
``owner_user_id`` (set at scan time from the signed-in user); this helper
denies access when a record is owned by someone else.

Records persisted before ownership tracking (``owner_user_id=None``,
including anonymous scans) keep the legacy tenant-only behavior — ownership
can't be retroactively attributed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from app.history.scan_record import ScanRecord


def assert_scan_access(record: "ScanRecord", request: Request) -> None:
    """Raise 404 unless the request's user may access this scan record."""
    owner = getattr(record, "owner_user_id", None)
    if not owner:
        return
    # Deferred: app.oauth pulls in app.main-adjacent modules at import time.
    from app.oauth import current_user

    user = current_user(request)
    if user is None or user.id != owner:
        # 404, not 403: don't confirm the scan exists to non-owners.
        raise HTTPException(status_code=404, detail="Scan not found")
