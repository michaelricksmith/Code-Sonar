"""Runtime providers used by Ask Sonar grounding and answer generation.

The default scan provider reads an already-persisted, redacted ScanRecord. The
answer provider is always explicit: Ask Sonar never silently selects or trains a
model and never grants a text-generation provider direct repository access.
"""

from __future__ import annotations

import os
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


def configure_answer_provider_from_env() -> None:
    """Configure the explicitly selected Ask Sonar provider from environment.

    No provider is selected by default. Setting ``CODE_SONAR_ASK_PROVIDER`` to
    ``ollama`` creates the local adapter but does not make a network request.
    """
    provider_name = os.getenv("CODE_SONAR_ASK_PROVIDER", "").strip().lower()
    if not provider_name:
        set_answer_provider(None)
        return
    if provider_name != "ollama":
        raise ValueError(f"Unsupported Ask Sonar provider: {provider_name}")

    from app.ask_sonar.providers import OllamaAnswerProvider

    model_name = os.getenv("CODE_SONAR_OLLAMA_MODEL", "llama3.1:8b").strip()
    base_url = os.getenv("CODE_SONAR_OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
    timeout_raw = os.getenv("CODE_SONAR_OLLAMA_TIMEOUT_SECONDS", "45").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("CODE_SONAR_OLLAMA_TIMEOUT_SECONDS must be numeric") from exc
    if timeout_seconds <= 0:
        raise ValueError("CODE_SONAR_OLLAMA_TIMEOUT_SECONDS must be positive")
    if not model_name:
        raise ValueError("CODE_SONAR_OLLAMA_MODEL must be non-empty")
    if not base_url:
        raise ValueError("CODE_SONAR_OLLAMA_BASE_URL must be non-empty")

    set_answer_provider(
        OllamaAnswerProvider(
            model_name=model_name,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    )


configure_answer_provider_from_env()
