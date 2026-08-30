"""Runtime providers used by Ask Sonar grounding and answer generation.

The default scan provider reads an already-persisted, redacted ScanRecord. The
answer provider is always explicit: Ask Sonar never silently selects or trains a
model and never grants a text-generation provider direct repository access.
"""

from __future__ import annotations

from typing import Callable

from app.ask_sonar.answering import AnswerProviderProtocol
from app.history import JsonlHistoryStore, ScanRecord

ScanProvider = Callable[[str], ScanRecord | None]
_scan_provider: ScanProvider | None = None
_answer_provider: AnswerProviderProtocol | None = None


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


def set_answer_provider(provider: AnswerProviderProtocol | None) -> None:
    """Set the approved text-generation provider for Ask Sonar."""
    global _answer_provider
    _answer_provider = provider


def get_answer_provider() -> AnswerProviderProtocol | None:
    """Return the explicitly configured Ask Sonar answer provider, if any."""
    return _answer_provider
