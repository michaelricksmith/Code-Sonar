"""Process-wide scan history store used by API and background workflows."""

from app.history import InMemoryHistoryStore, JsonlHistoryStore

HistoryStore = JsonlHistoryStore | InMemoryHistoryStore

_history_store: HistoryStore = JsonlHistoryStore()


def get_history_store() -> HistoryStore:
    """Return the active history store."""
    return _history_store


def set_history_store(store: HistoryStore) -> None:
    """Replace the active history store. Primarily used by tests."""
    global _history_store
    _history_store = store
