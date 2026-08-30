"""Runtime access to remediation outcome persistence."""

from __future__ import annotations

from app.ml.outcomes.store import JsonlOutcomeStore

_outcome_store: JsonlOutcomeStore | None = None


def set_outcome_store(store: JsonlOutcomeStore | None) -> None:
    """Override outcome persistence, primarily for tests and executors."""
    global _outcome_store
    _outcome_store = store


def get_outcome_store() -> JsonlOutcomeStore:
    """Return configured outcome persistence without performing any execution."""
    return _outcome_store or JsonlOutcomeStore()
