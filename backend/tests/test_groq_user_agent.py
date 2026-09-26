"""Groq calls must carry an explicit User-Agent.

Regression guard: Groq sits behind Cloudflare, which rejects urllib's
default "Python-urllib/3.x" signature with HTTP 403 / error code 1010
before the API key is even read. Without this header, every Groq call from
the hosted service fails and looks exactly like an auth failure.
"""

from __future__ import annotations

import io
import json
import urllib.request

import app.ask_sonar.providers.openai_compatible as oc
import app.remediation.groq as groq_mod


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = io.BytesIO(body)

    def read(self) -> bytes:
        return self._body.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _capture_urlopen(monkeypatch, body: bytes):
    """Mock only urlopen: everything up to the socket stays real."""
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["request"] = req
        return _FakeResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    return captured


def test_ask_sonar_sends_user_agent(monkeypatch):
    answer_body = json.dumps(
        {
            "choices": [
                {"message": {"content": json.dumps({"answer": "ok", "used_sources": []})}}
            ]
        }
    ).encode()
    captured = _capture_urlopen(monkeypatch, answer_body)

    provider = oc.OpenAICompatibleProvider(
        api_key="test-key",
        model_name="openai/gpt-oss-120b",
        base_url="https://api.groq.com/openai/v1",
    )
    provider.answer("q", {"allowed_sources": []})

    ua = captured["request"].get_header("User-agent")
    assert ua == "Code-Sonar/1.0", f"User-Agent missing or wrong: {ua!r}"


def test_remediation_groq_sends_user_agent(monkeypatch):
    completion_body = json.dumps({"choices": [{"message": {"content": "fixed"}}]}).encode()
    captured = _capture_urlopen(monkeypatch, completion_body)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    groq_mod._call_groq("fix this")

    ua = captured["request"].get_header("User-agent")
    assert ua == "Code-Sonar/1.0", f"User-Agent missing or wrong: {ua!r}"
