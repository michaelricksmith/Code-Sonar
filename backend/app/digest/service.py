"""Weekly digest email: content generation for retention Phase 3.

Copyright © 2026 Michael Smith. All rights reserved.

Builds the per-user weekly code health digest: score trend per repo,
fixes verified that week, open issues remaining, and one clear call to
action. Every number comes from real stored state — never invent activity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.fix_tracking.runtime import get_fix_attempt_store
from app.fix_tracking.service import _parse_week_start


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_repos(user_id: str, history_store: Any) -> dict[str, list[Any]]:
    """All scan records grouped by repo for repos the user owns or touched."""
    by_repo: dict[str, list[Any]] = {}
    for record in history_store.load_all():
        if record.owner_user_id != user_id:
            continue
        by_repo.setdefault(record.repository_id, []).append(record)
    # Also include repos where the user copied a fix prompt but doesn't own
    # the scan (team repos).
    try:
        attempts = get_fix_attempt_store().list_by_user(user_id)
    except Exception:
        attempts = []
    touched = {a.repository_id for a in attempts} - set(by_repo)
    for repo_id in touched:
        records = history_store.load_all(repo_id)
        if records:
            by_repo[repo_id] = records
    for records in by_repo.values():
        records.sort(key=lambda r: r.scanned_at)
    return by_repo


def _repo_digest_entry(records: list[Any]) -> dict[str, Any]:
    latest = records[-1]
    drift = latest.drift_summary or {}
    return {
        "repository_id": latest.repository_id,
        "repository_label": latest.repository_slug
        or latest.repository_path.rsplit("/", 1)[-1],
        "score": latest.score,
        "grade": latest.grade,
        "finding_count": latest.finding_count,
        "scanned_at": latest.scanned_at,
        "score_delta": drift.get("score_delta"),
        "new_count": drift.get("new_count", 0),
        "resolved_count": drift.get("resolved_count", 0),
        "scan_count": len(records),
    }


def build_digest(user_id: str, history_store: Any) -> dict[str, Any]:
    """Build the weekly digest content for a user.

    Returns an empty-digest marker when the user has no repo activity —
    callers should skip sending rather than send an empty email.
    """
    by_repo = _user_repos(user_id, history_store)
    if not by_repo:
        return {"user_id": user_id, "has_activity": False, "repos": []}

    week_start = _parse_week_start(_utcnow().isoformat())
    try:
        attempts = get_fix_attempt_store().list_by_user(user_id, verified_only=True)
    except Exception:
        attempts = []
    verified_this_week = [
        a for a in attempts if _parse_week_start(a.verified_at or "") == week_start
    ]

    repos = [_repo_digest_entry(records) for records in by_repo.values()]
    repos.sort(key=lambda r: r["finding_count"], reverse=True)

    total_open = sum(r["finding_count"] for r in repos)
    # One clear call to action: the repo with the most open issues.
    cta_repo = repos[0] if repos else None

    return {
        "user_id": user_id,
        "has_activity": True,
        "week_start": week_start,
        "repos": repos,
        "total_repos": len(repos),
        "total_open_issues": total_open,
        "verified_this_week": len(verified_this_week),
        "cta": (
            {
                "repository_label": cta_repo["repository_label"],
                "finding_count": cta_repo["finding_count"],
                "text": (
                    f"{cta_repo['repository_label']} has "
                    f"{cta_repo['finding_count']} open "
                    f"{'issue' if cta_repo['finding_count'] == 1 else 'issues'} — "
                    "run a scan and grab a fix prompt to knock them out."
                ),
            }
            if cta_repo and cta_repo["finding_count"] > 0
            else None
        ),
    }
