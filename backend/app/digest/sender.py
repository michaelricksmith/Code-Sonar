"""Weekly digest sender (Phase 3).

Copyright © 2026 Michael Smith. All rights reserved.

Sends the weekly code health digest to every opted-in user with repo
activity. Run weekly via cron. Never sends to unsubscribed users, never
sends empty digests, and stops entirely when Resend is not configured.

Usage: python -m app.digest.sender [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

sys.path.insert(0, ".")


def _users_with_activity(history_store: Any) -> list[str]:
    users: set[str] = set()
    for record in history_store.load_all():
        if record.owner_user_id:
            users.add(record.owner_user_id)
    return sorted(users)


def send_weekly_digest(*, dry_run: bool = False) -> dict[str, int]:
    from app.digest.preferences import (
        get_email_preference_store,
        unsubscribe_token,
    )
    from app.digest.resend_client import (
        EmailNotConfiguredError,
        is_configured,
        send_email,
    )
    from app.digest.service import build_digest
    from app.digest.templates import render_html, render_text
    from app.main import get_history_store
    from app.oauth import get_oauth_user_store

    history_store = get_history_store()
    prefs = get_email_preference_store()
    user_store = get_oauth_user_store()

    stats = {"considered": 0, "sent": 0, "skipped_no_activity": 0,
             "skipped_opted_out": 0, "skipped_no_email": 0, "failed": 0}

    if not dry_run and not is_configured():
        raise EmailNotConfiguredError(
            "RESEND_API_KEY / DIGEST_FROM_ADDRESS not set; refusing to run"
        )

    for user_id in _users_with_activity(history_store):
        stats["considered"] += 1
        if not prefs.is_digest_enabled(user_id):
            stats["skipped_opted_out"] += 1
            continue
        user = user_store.get(user_id)
        if user is None or not getattr(user, "email", None):
            stats["skipped_no_email"] += 1
            continue
        digest = build_digest(user_id, history_store)
        if not digest.get("has_activity"):
            stats["skipped_no_activity"] += 1
            continue
        token = unsubscribe_token(user_id)
        unsubscribe_url = (
            "https://code-sonar.onrender.com/api/digest/unsubscribe?token=" + token
        )
        subject = (
            f"Your weekly code health report: "
            f"{digest['total_open_issues']} open "
            f"{'issue' if digest['total_open_issues'] == 1 else 'issues'}"
        )
        if dry_run:
            stats["sent"] += 1  # Would have sent.
            continue
        try:
            send_email(
                to=user.email,
                subject=subject,
                html=render_html(digest, unsubscribe_url),
                text=render_text(digest, unsubscribe_url),
                tags={"kind": "weekly-digest"},
            )
            stats["sent"] += 1
        except Exception:
            stats["failed"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the weekly digest email.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count who would receive it; send nothing.")
    args = parser.parse_args()
    from app.security.tenant import bind_tenant

    token = bind_tenant("local")
    try:
        stats = send_weekly_digest(dry_run=args.dry_run)
    finally:
        from app.security.tenant import reset_tenant

        reset_tenant(token)
    print(stats)


if __name__ == "__main__":
    main()
