"""Tests for hosted Ask Sonar providers, registry, and BYOK headers."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.ask_sonar.api as ask_api
from app.ask_sonar.answering import GroundedAnswer
from app.ask_sonar.providers import AnthropicProvider, OpenAICompatibleProvider
from app.ask_sonar.runtime import (
    build_transient_byok_provider,
    set_answer_provider,
    set_scan_provider,
)
from app.history import ScanRecord
from app.main import app
from app.ml.runtime import clear_prediction_models, clear_similarity_indexes


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "ASK_SONAR_PROVIDER",
        "CODE_SONAR_ASK_PROVIDER",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ASK_SONAR_BASE_URL",
        "ASK_SONAR_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    set_scan_provider(None)
    set_answer_provider(None)
    clear_prediction_models()
    clear_similarity_indexes()
    yield
    set_scan_provider(None)
    set_answer_provider(None)
    clear_prediction_models()
    clear_similarity_indexes()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _record() -> ScanRecord:
    return ScanRecord(
        scan_id="scan-1",
        repository_id="repo-1",
        repository_path="example/repo",
        scanned_at="2026-08-30T20:00:00+00:00",
        schema_version="1.0",
        score=720,
        grade="B",
        total_debt_points=30,
        finding_count=0,
        category_scores={"maintainability": 700},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={"source": 0, "test": 0, "fixture": 0},
        findings=[],
    )


def _grounded_body(answer: str = "Plain-language answer.") -> bytes:
    return json.dumps(
        {"answer": answer, "used_sources": ["deterministic"]}
    ).encode("utf-8")


class TestOpenAICompatibleProvider:
    def test_answer_posts_to_chat_completions_with_bearer_key(self) -> None:
        seen: dict[str, Any] = {}

        def transport(url: str, payload: bytes, timeout: float, headers) -> bytes:
            seen["url"] = url
            seen["headers"] = dict(headers)
            body = json.loads(payload.decode("utf-8"))
            seen["body"] = body
            content = _grounded_body()
            return json.dumps(
                {"choices": [{"message": {"content": content.decode("utf-8")}}]}
            ).encode("utf-8")

        provider = OpenAICompatibleProvider(
            api_key="sk-test",
            model_name="gpt-4o-mini",
            transport=transport,
        )
        result = provider.answer(
            "Why is my score a B?", {"allowed_sources": ["deterministic"]}
        )
        assert isinstance(result, GroundedAnswer)
        assert result.answer == "Plain-language answer."
        assert result.used_sources == ("deterministic",)
        assert result.provider_name == "openai"
        assert seen["url"] == "https://api.openai.com/v1/chat/completions"
        assert seen["headers"]["Authorization"] == "Bearer sk-test"
        # Plain-language system instruction is part of the request.
        system_text = seen["body"]["messages"][0]["content"]
        assert "plain language" in system_text
        assert "non-technical" in system_text

    def test_custom_base_url_is_used(self) -> None:
        seen: dict[str, Any] = {}

        def transport(url: str, payload: bytes, timeout: float, headers) -> bytes:
            seen["url"] = url
            return json.dumps(
                {"choices": [{"message": {"content": _grounded_body().decode()}}]}
            ).encode("utf-8")

        provider = OpenAICompatibleProvider(
            api_key="k",
            base_url="https://gateway.example.com/v1/",
            transport=transport,
        )
        provider.answer("q", {"allowed_sources": ["deterministic"]})
        assert seen["url"] == "https://gateway.example.com/v1/chat/completions"

    def test_invalid_payload_raises_value_error(self) -> None:
        def transport(url: str, payload: bytes, timeout: float, headers) -> bytes:
            return b'{"choices": []}'

        provider = OpenAICompatibleProvider(api_key="k", transport=transport)
        with pytest.raises(ValueError):
            provider.answer("q", {"allowed_sources": ["deterministic"]})


class TestAnthropicProvider:
    def test_answer_posts_to_messages_api(self) -> None:
        seen: dict[str, Any] = {}

        def transport(url: str, payload: bytes, timeout: float, headers) -> bytes:
            seen["url"] = url
            seen["headers"] = dict(headers)
            body = json.loads(payload.decode("utf-8"))
            seen["body"] = body
            return json.dumps(
                {"content": [{"type": "text", "text": _grounded_body().decode()}]}
            ).encode("utf-8")

        provider = AnthropicProvider(api_key="anthro-test", transport=transport)
        result = provider.answer(
            "Why is my score a B?", {"allowed_sources": ["deterministic"]}
        )
        assert result.answer == "Plain-language answer."
        assert result.provider_name == "anthropic"
        assert seen["url"] == "https://api.anthropic.com/v1/messages"
        assert seen["headers"]["x-api-key"] == "anthro-test"
        assert seen["headers"]["anthropic-version"] == "2023-06-01"
        assert "plain language" in seen["body"]["system"]

    def test_invalid_payload_raises_value_error(self) -> None:
        def transport(url: str, payload: bytes, timeout: float, headers) -> bytes:
            return b'{"content": []}'

        provider = AnthropicProvider(api_key="k", transport=transport)
        with pytest.raises(ValueError):
            provider.answer("q", {"allowed_sources": ["deterministic"]})


class TestTransientByokBuilder:
    def test_unknown_provider_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_transient_byok_provider("gemini", "key")

    def test_missing_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_transient_byok_provider("openai", "")

    def test_openai_and_anthropic_build(self) -> None:
        openai_provider = build_transient_byok_provider("openai", "sk-x")
        assert openai_provider.provider_name == "openai"
        assert openai_provider.api_key == "sk-x"  # held in memory only
        anthropic_provider = build_transient_byok_provider("anthropic", "ak-x")
        assert anthropic_provider.provider_name == "anthropic"


class TestProviderRegistry:
    def test_registry_lists_all_providers(self, client, monkeypatch) -> None:
        response = client.get("/api/ask-sonar/providers")
        assert response.status_code == 200
        providers = {p["name"]: p for p in response.json()["providers"]}
        assert providers["ollama"] == {
            "name": "ollama",
            "label": "Ollama (self-hosted)",
            "configured": True,
            "source": "ollama",
        }
        assert providers["openai"]["configured"] is False
        assert providers["openai"]["source"] == "unconfigured"

    def test_registry_reflects_env_keys(self, client, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-env")
        providers = {
            p["name"]: p for p in client.get("/api/ask-sonar/providers").json()["providers"]
        }
        assert providers["openai"]["configured"] is True
        assert providers["openai"]["source"] == "env"
        assert providers["anthropic"]["configured"] is True
        assert providers["anthropic"]["source"] == "env"


class TestByokHeaders:
    def _mock_byok_transport(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        real_builder = ask_api.build_transient_byok_provider

        def transport(url: str, payload: bytes, timeout: float, headers) -> bytes:
            seen["headers"] = dict(headers)
            return json.dumps(
                {"choices": [{"message": {"content": _grounded_body().decode()}}]}
            ).encode("utf-8")

        def fake_builder(name: str, key: str):
            provider = real_builder(name, key)
            provider.transport = transport  # type: ignore[attr-defined]
            return provider

        monkeypatch.setattr(ask_api, "build_transient_byok_provider", fake_builder)
        set_scan_provider(lambda scan_id: _record() if scan_id == "scan-1" else None)
        return seen

    def test_ask_with_byok_headers_uses_transient_provider(
        self, client, monkeypatch
    ) -> None:
        seen = self._mock_byok_transport(monkeypatch)
        response = client.post(
            "/api/ask-sonar/ask",
            json={"scan_id": "scan-1", "question": "Why is my score a B?"},
            headers={"X-AI-Provider": "openai", "X-AI-API-Key": "sk-byok"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["answer"]["answer"] == "Plain-language answer."
        assert data["answer"]["provider_name"] == "openai"
        assert seen["headers"]["Authorization"] == "Bearer sk-byok"
        # The key is never echoed back.
        assert "sk-byok" not in response.text

    def test_ask_byok_provider_without_key_is_400(self, client) -> None:
        set_scan_provider(lambda scan_id: _record())
        response = client.post(
            "/api/ask-sonar/ask",
            json={"scan_id": "scan-1", "question": "q"},
            headers={"X-AI-Provider": "openai"},
        )
        assert response.status_code == 400

    def test_ask_byok_unknown_provider_is_400(self, client) -> None:
        set_scan_provider(lambda scan_id: _record())
        response = client.post(
            "/api/ask-sonar/ask",
            json={"scan_id": "scan-1", "question": "q"},
            headers={"X-AI-Provider": "gemini", "X-AI-API-Key": "k"},
        )
        assert response.status_code == 400

    def test_ask_unconfigured_names_what_is_missing(self, client) -> None:
        set_scan_provider(lambda scan_id: _record())
        response = client.post(
            "/api/ask-sonar/ask",
            json={"scan_id": "scan-1", "question": "q"},
        )
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "ask_sonar_provider_unavailable"
        assert "OPENAI_API_KEY" in detail["message"]
        assert "ANTHROPIC_API_KEY" in detail["message"]
        assert "ollama" in detail["message"]
