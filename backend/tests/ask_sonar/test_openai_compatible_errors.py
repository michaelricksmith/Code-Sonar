"""Ask Sonar OpenAI-compatible provider surfaces upstream error bodies.

Regression guard for the September 2026 Groq outage: the transport used to
report only the HTTP status ("OpenAI-compatible request failed (HTTP 403)"),
which sent debugging down the wrong path (blamed the model; the key was the
problem). The upstream error body names the real cause and must be included.
"""

from __future__ import annotations

import io
import json
from urllib import error

import pytest

import app.ask_sonar.providers.openai_compatible as oc


def _http_error(code: int, body: bytes | None) -> error.HTTPError:
    fp = io.BytesIO(body) if body is not None else None
    return error.HTTPError(
        url="https://api.groq.com/openai/v1/chat/completions",
        code=code,
        msg="Forbidden",
        hdrs={},
        fp=fp,
    )


def _run_with_failing_post(monkeypatch, exc: error.HTTPError) -> None:
    def _fail(url, payload, timeout_seconds, headers):
        raise exc

    monkeypatch.setattr(oc, "_single_post", _fail)
    oc._default_transport("https://example.invalid/chat/completions", b"{}", 1.0, {})


def test_403_includes_upstream_error_body(monkeypatch):
    body = json.dumps(
        {"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}
    ).encode()
    with pytest.raises(RuntimeError, match=r"HTTP 403.*Invalid API Key"):
        _run_with_failing_post(monkeypatch, _http_error(403, body))


def test_403_without_body_still_reports_status(monkeypatch):
    with pytest.raises(RuntimeError, match=r"HTTP 403.*no error body"):
        _run_with_failing_post(monkeypatch, _http_error(403, None))
