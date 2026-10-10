"""Per-scan ownership enforcement (cross-tenant IDOR fix).

Session-cookie users share the ``"local"`` tenant, so the tenant check alone
cannot tell users apart: any signed-in user could previously read, query, and
run remediation against any other user's scan. Scan records now carry
``owner_user_id`` (set at scan time from the signed-in user).

Access model:

- **Owned scans** (``owner_user_id`` set): visible only to the owning user —
  in single reads, listings, and drift pairs.
- **Ownerless scans** (``owner_user_id=None``: anonymous scans and records
  persisted before ownership tracking): reachable only by direct ``scan_id``
  lookup. Scan ids are 128-bit unguessable, so presenting one is a bearer
  capability — the person who ran the scan received it in the scan response.
  Ownerless scans never appear in listings, so one user can no longer
  enumerate another user's scans.
- **Claiming**: a signed-in user who holds an ownerless scan's ``scan_id``
  may claim it via ``POST /api/history/{scan_id}/claim``, which attributes
  ownership and restores listing visibility. Claiming someone else's owned
  scan is rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from app.history.scan_record import ScanRecord


def _request_user_id(request: Request) -> str | None:
    # Deferred: app.oauth pulls in app.main-adjacent modules at import time.
    try:
        from app.oauth import current_user
    except Exception:
        return None
    try:
        user = current_user(request)
    except Exception:
        return None
    return user.id if user is not None else None


def assert_scan_access(record: "ScanRecord", request: Request) -> None:
    """Raise 404 unless the request's user may access this scan record.

    Ownerless records are accessible to whoever presents the unguessable
    scan id (bearer capability); owned records only to their owner.
    """
    owner = getattr(record, "owner_user_id", None)
    if not owner:
        return
    if _request_user_id(request) != owner:
        # 404, not 403: don't confirm the scan exists to non-owners.
        raise HTTPException(status_code=404, detail="Scan not found")


def visible_scans(records: list["ScanRecord"], request: Request) -> list["ScanRecord"]:
    """Return the subset of ``records`` the request's user may enumerate.

    Only scans owned by the signed-in user are listable. Ownerless scans
    stay reachable by direct scan-id lookup (bearer capability) but are
    excluded here so users cannot enumerate each other's scans.

    Requests authenticated with a server-owned bearer token run in a
    non-local tenant whose store view is already tenant-scoped, so the
    OAuth ownership filter does not apply to them.
    """
    try:
        from app.security.tenant import LOCAL_TENANT_ID, current_tenant_id

        if current_tenant_id() != LOCAL_TENANT_ID:
            return list(records)
    except Exception:
        pass
    user_id = _request_user_id(request)
    if user_id is None:
        return []
    return [r for r in records if getattr(r, "owner_user_id", None) == user_id]
