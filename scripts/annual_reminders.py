#!/usr/bin/env python3
"""Send CA AB 2863 annual renewal reminders to due paid subscribers.

Usage:
    python scripts/annual_reminders.py --list   # show who is due
    python scripts/annual_reminders.py --send   # send + record

Run monthly from a scheduler. Email goes through SONAR_EMAIL_TRANSPORT
(log | smtp | resend); the default log transport renders the messages
without sending — configure a real transport before the first paid
subscriber's 11-month mark.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.compliance.reminders import due_annual_reminders, send_annual_reminder
from app.oauth import OAuthUserStore, get_oauth_user_store
from app.persistence.runtime import configure_persistence_from_env


def _all_users() -> list:
    store = None
    if os.environ.get("CODESONAR_DATABASE_URL", "").strip():
        try:
            persistence = configure_persistence_from_env()
            if persistence is not None:
                store = get_oauth_user_store()
        except Exception as exc:  # noqa: BLE001 - fall back to JSON below
            print(f"persistence wiring failed ({exc}); using local JSON store")
    if store is None:
        store = OAuthUserStore()
    if hasattr(store, "list_users"):
        users, offset = [], 0
        while True:
            page = store.list_users(limit=500, offset=offset)
            if not page:
                break
            users.extend(page)
            offset += len(page)
        return users
    return store.load_all()


def main() -> int:
    parser = argparse.ArgumentParser(description="Annual renewal reminders")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List due users")
    group.add_argument("--send", action="store_true", help="Send reminders + record")
    args = parser.parse_args()

    due = due_annual_reminders(_all_users())
    if args.list:
        if not due:
            print("No users are due an annual reminder.")
            return 0
        for entry in due:
            print(
                f"{entry['email']}  plan={entry['plan']}  "
                f"last_reminder={entry['last_reminder_at'] or 'never'}"
            )
        return 0

    sent = 0
    for entry in due:
        try:
            receipt = send_annual_reminder(entry)
        except Exception as exc:  # noqa: BLE001 - keep going, report at end
            print(f"FAILED {entry['email']}: {exc}", file=sys.stderr)
            continue
        sent += 1
        print(f"sent to {entry['email']} via {receipt.get('transport')}")
    print(f"{sent}/{len(due)} reminders sent.")
    return 0 if sent == len(due) else 1


if __name__ == "__main__":
    raise SystemExit(main())
