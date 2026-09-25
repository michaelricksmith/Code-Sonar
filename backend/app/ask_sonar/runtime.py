"""Runtime providers used by Ask Sonar grounding and answer generation.

The default scan provider reads an already-persisted, redacted ScanRecord. The
answer provider is always explicit: Ask Sonar never silently selects or trains a
model and never grants a text-generation provider direct repository access.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable

from app.ask_sonar.answering import AnswerProviderProtocol
from app.history import ScanRecord

if TYPE_CHECKING:
    from app.ask_sonar.providers import (
        AnthropicProvider,
        OllamaAnswerProvider,
        OpenAICompatibleProvider,
    )

ScanProvider = Callable[[str], ScanRecord | None]
_scan_provider: ScanProvider | None = None
_answer_provider: AnswerProviderProtocol | None = None


def set_scan_provider(provider: ScanProvider | None) -> None:
    """Override stored-scan lookup; primarily used by tests/session wiring."""
    global _scan_provider
    _scan_provider = provider


def _persisted_scan(scan_id: str) -> ScanRecord | None:
    from app.main import get_history_store

    return get_history_store().get(scan_id)


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


def _ollama_provider_from_env() -> OllamaAnswerProvider:
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

    return OllamaAnswerProvider(
        model_name=model_name,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def _openai_provider_from_env(*, api_key: str) -> OpenAICompatibleProvider:
    from app.ask_sonar.providers import OpenAICompatibleProvider

    if not api_key:
        raise ValueError(
            "ASK_SONAR_PROVIDER=openai requires OPENAI_API_KEY to be set"
        )
    base_url = os.getenv("ASK_SONAR_BASE_URL", "https://api.openai.com/v1").strip()
    model_name = os.getenv("ASK_SONAR_MODEL", "gpt-4o-mini").strip()
    if not base_url:
        raise ValueError("ASK_SONAR_BASE_URL must be non-empty")
    if not model_name:
        raise ValueError("ASK_SONAR_MODEL must be non-empty")
    return OpenAICompatibleProvider(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
    )


def _anthropic_provider_from_env(*, api_key: str) -> AnthropicProvider:
    from app.ask_sonar.providers import AnthropicProvider

    if not api_key:
        raise ValueError(
            "ASK_SONAR_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set"
        )
    model_name = os.getenv("ASK_SONAR_MODEL", "claude-haiku-4-5").strip()
    if not model_name:
        raise ValueError("ASK_SONAR_MODEL must be non-empty")
    return AnthropicProvider(api_key=api_key, model_name=model_name)


_SUPPORTED_PROVIDERS = ("ollama", "openai", "anthropic")


def configure_answer_provider_from_env() -> None:
    """Configure the explicitly selected Ask Sonar provider from environment.

    Selection: ASK_SONAR_PROVIDER, falling back to the legacy
    CODE_SONAR_ASK_PROVIDER for backward compatibility. No provider is selected
    by default. Supported values: ollama (self-hosted), openai
    (OpenAI-compatible, needs OPENAI_API_KEY), anthropic (needs
    ANTHROPIC_API_KEY). Configuring a provider makes no network request.
    """
    provider_name = (
        os.getenv("ASK_SONAR_PROVIDER", "").strip().lower()
        or os.getenv("CODE_SONAR_ASK_PROVIDER", "").strip().lower()
    )
    if not provider_name:
        set_answer_provider(None)
        return
    if provider_name not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported Ask Sonar provider: {provider_name}")

    if provider_name == "ollama":
        set_answer_provider(_ollama_provider_from_env())
    elif provider_name == "openai":
        set_answer_provider(
            _openai_provider_from_env(
                api_key=(
                    os.getenv("OPENAI_API_KEY", "").strip()
                    or os.getenv("GROQ_API_KEY", "").strip()
                )
            )
        )
    elif provider_name == "anthropic":
        set_answer_provider(
            _anthropic_provider_from_env(
                api_key=os.getenv("ANTHROPIC_API_KEY", "").strip()
            )
        )


def build_transient_byok_provider(
    provider_name: str, api_key: str
) -> AnswerProviderProtocol:
    """Build a single-request provider from BYOK headers.

    The key is used for this request only: it is held in memory on the
    provider instance and is never persisted or logged. Ollama is
    self-hosted and needs no API key.
    """
    normalized = (provider_name or "").strip().lower()
    if normalized == "ollama":
        return _ollama_provider_from_env()
    if normalized not in ("openai", "anthropic"):
        raise ValueError(
            "Unsupported X-AI-Provider: use 'ollama', 'openai' or 'anthropic'"
        )
    if not api_key:
        raise ValueError("X-AI-API-Key is required when X-AI-Provider is set")
    if normalized == "openai":
        return _openai_provider_from_env(api_key=api_key)
    return _anthropic_provider_from_env(api_key=api_key)


def get_provider_registry() -> list[dict[str, object]]:
    """Describe available Ask Sonar providers without contacting any of them.

    Ollama is reported as configured only when the operator selected it via
    ASK_SONAR_PROVIDER=ollama. It is never assumed reachable: claiming a
    phantom provider as "AI ready" sends the frontend down a header path the
    backend then rejects.
    """
    env_provider = os.getenv("ASK_SONAR_PROVIDER", "").strip().lower()
    ollama_configured = env_provider == "ollama"
    openai_configured = bool(
        os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("GROQ_API_KEY", "").strip()
    )
    anthropic_configured = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    return [
        {
            "name": "ollama",
            "label": "Ollama (self-hosted)",
            "configured": ollama_configured,
            "source": "ollama" if ollama_configured else "unconfigured",
        },
        {
            "name": "openai",
            "label": "OpenAI",
            "configured": openai_configured,
            "source": "env" if openai_configured else "unconfigured",
        },
        {
            "name": "anthropic",
            "label": "Anthropic",
            "configured": anthropic_configured,
            "source": "env" if anthropic_configured else "unconfigured",
        },
    ]


configure_answer_provider_from_env()
