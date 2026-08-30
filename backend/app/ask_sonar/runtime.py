"""Runtime providers used by Ask Sonar grounding.

The default provider reads an already-persisted, redacted ScanRecord. Tests and
future workspace/session layers can inject a different provider without changing
the grounding contract.
"""

from __future__ import annotations

from typing import Callable

from app.history import JsonlHistoryStore, ScanRecord

ScanProvider = Callable[[str], ScanRecord | None]
_scan_provider: ScanProvider | None = None


def set_scan_provider(provider: ScanProvider | None) -> None:
    """Override stored-scan lookup; primarily used by tests/session wiring."""
    global _scan_provider
    _scan_provider = provider


def _persisted_scan(scan_id: str) -> ScanRecord | None:
    return JsonlHistoryStore().get(scan_id)


def get_scan(scan_id: str) -> ScanRecord | None:
    """Resolve an existing scan without triggering a repository scan."""
    provider = _scan_provider or _persisted_scan
    return provider(scan_id)
