"""Runtime registry for the fix-attempt store.

Copyright © 2026 Michael Smith. All rights reserved.

Mirrors ``app.ml.outcomes.runtime``: an in-memory store by default,
replaced with the SQL store when persistence is configured.
"""

from __future__ import annotations

from app.fix_tracking.store import FixAttemptStore, InMemoryFixAttemptStore

_store: FixAttemptStore = InMemoryFixAttemptStore()


def get_fix_attempt_store() -> FixAttemptStore:
    """Return the process-wide fix-attempt store."""
    return _store


def set_fix_attempt_store(store: FixAttemptStore) -> None:
    """Replace the process-wide fix-attempt store. Used at startup and by tests."""
    global _store
    _store = store
