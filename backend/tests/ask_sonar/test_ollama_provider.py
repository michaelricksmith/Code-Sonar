"""Tests for the local Ollama Ask Sonar provider adapter."""

from __future__ import annotations

import json

import pytest

from app.ask_sonar.providers import OllamaAnswerProvider
from app.ask_sonar.runtime import (
    configure_answer_provider_from_env,
    get_answer_provider,
    set_answer_provider,
)


@pytest.fixture(autouse=True)
def reset_answer_provider():
    set_answer_provider(None)
    yield
    set_answer_provider(None)


def _context() -> dict[str, object]:
    return {
        "context_schema_version": "1.0",
        "scan_id": "scan-1",
        "allowed_sources": ["deterministic"],
        "source_policy": {
            "deterministic_is_authoritative": True,
            "ml_is_advisory": True,
        },
        "deterministic": {"score": 720, "grade": "B"},
        "ml_prediction": {"status": "unavailable"},
        "historical_similarity": {"status": "unavailable"},
    }


def test_ollama_provider_sends_grounded_json_prompt() -> None:
    captured: dict[str, object] = {}

    def transport(url: str, payload: bytes, timeout: float) -> bytes:
        captured["url"] = url
        captured["timeout"] = timeout
        request_body = json.loads(payload.decode("utf-8"))
        captured["request"] = request_body
        return json.dumps(
            {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": "The deterministic score is 720, grade B.",
                            "used_sources": ["deterministic"],
                        }
                    )
                }
            }
        ).encode("utf-8")

    provider = OllamaAnswerProvider(
        model_name="llama-test",
        base_url="http://127.0.0.1:11434/",
        timeout_seconds=12.0,
        transport=transport,
    )

    result = provider.answer("Why is my score a B?", _context())

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 12.0
    request_body = captured["request"]
    assert isinstance(request_body, dict)
    assert request_body["model"] == "llama-test"
    assert request_body["stream"] is False
    assert request_body["format"] == "json"
    prompt = request_body["messages"][0]["content"]
    assert "Allowed sources: [\"deterministic\"]" in prompt
    assert "Never invent repository facts" in prompt
    assert result.answer == "The deterministic score is 720, grade B."
    assert result.used_sources == ("deterministic",)
    assert result.provider_name == "ollama"


def test_ollama_provider_rejects_invalid_response_shape() -> None:
    def transport(url: str, payload: bytes, timeout: float) -> bytes:
        return json.dumps({"message": {"content": "not-json"}}).encode("utf-8")

    provider = OllamaAnswerProvider(transport=transport)

    with pytest.raises(ValueError, match="invalid grounded-answer payload"):
        provider.answer("Question", _context())


def test_environment_configuration_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SONAR_ASK_PROVIDER", raising=False)
    configure_answer_provider_from_env()
    assert get_answer_provider() is None

    monkeypatch.setenv("CODE_SONAR_ASK_PROVIDER", "ollama")
    monkeypatch.setenv("CODE_SONAR_OLLAMA_MODEL", "llama-local")
    monkeypatch.setenv("CODE_SONAR_OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("CODE_SONAR_OLLAMA_TIMEOUT_SECONDS", "20")
    configure_answer_provider_from_env()

    provider = get_answer_provider()
    assert isinstance(provider, OllamaAnswerProvider)
    assert provider.model_name == "llama-local"
    assert provider.base_url == "http://localhost:11434"
    assert provider.timeout_seconds == 20.0


def test_environment_configuration_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODE_SONAR_ASK_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unsupported Ask Sonar provider"):
        configure_answer_provider_from_env()
