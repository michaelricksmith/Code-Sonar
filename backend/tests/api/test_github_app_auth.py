"""Unit tests for ``app.github_app`` — auth, install state, and signatures.

Companion files: ``tests/api/test_github_app.py`` covers the
installation/audit/scan-job stores; ``tests/api/test_github_app_dispatch.py``
covers the webhook payload/context/trigger helpers, the scan-job runner,
and the module-level setter/getter surface;
``tests/api/test_github_app_webhooks.py`` covers the ``/webhook`` route
end-to-end. This module covers ``GitHubAppAuth`` (JWT minting plus the
installation-detail/token HTTP calls against a fake client),
install-state signing, and webhook signature verification.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.github_app import (
    GitHubAppAuth,
    _INSTALL_STATE_TTL_SECONDS,
    _install_url,
    _issue_install_state,
    _verify_install_state,
    _verify_signature,
)

@dataclass
class _FakeGitHubResponse:
    payload: dict[str, Any] | None = None
    error: Exception | None = None

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self) -> dict[str, Any]:
        return dict(self.payload or {})

@dataclass
class _FakeGitHubClient:
    response: _FakeGitHubResponse
    calls: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)

    def get(
        self, url: str, headers: dict[str, str] | None = None
    ) -> _FakeGitHubResponse:
        self.calls.append(("get", url, dict(headers or {})))
        return self.response

    def post(
        self, url: str, headers: dict[str, str] | None = None
    ) -> _FakeGitHubResponse:
        self.calls.append(("post", url, dict(headers or {})))
        return self.response

def _rsa_private_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")

def _signed(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

# ---------------------------------------------------------------------------
# GitHubAppAuth
# ---------------------------------------------------------------------------

def test_auth_reports_configured_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SONAR_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("CODE_SONAR_GITHUB_APP_PRIVATE_KEY", raising=False)
    assert GitHubAppAuth().configured is False
    assert GitHubAppAuth(app_id="1", private_key="k").configured is True
    assert GitHubAppAuth(app_id="1").configured is False

def test_auth_jwt_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SONAR_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("CODE_SONAR_GITHUB_APP_PRIVATE_KEY", raising=False)
    with pytest.raises(PermissionError):
        GitHubAppAuth().app_jwt()

def test_auth_app_jwt_claims() -> None:
    before = time.time()
    token = GitHubAppAuth(app_id="12345", private_key=_rsa_private_pem()).app_jwt()
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "12345"
    assert abs(claims["iat"] - (before - 30)) <= 120
    assert abs(claims["exp"] - (before + 540)) <= 120

def test_auth_installation_details_sends_app_jwt() -> None:
    client = _FakeGitHubClient(_FakeGitHubResponse({"id": 42}))
    auth = GitHubAppAuth(app_id="1", private_key=_rsa_private_pem(), client=client)
    details = auth.installation_details(42)
    assert details == {"id": 42}
    method, url, headers = client.calls[0]
    assert method == "get"
    assert url == "https://api.github.com/app/installations/42"
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["X-GitHub-Api-Version"] == "2026-03-10"

def test_auth_installation_token_returns_token() -> None:
    client = _FakeGitHubClient(_FakeGitHubResponse({"token": "tok_123"}))
    auth = GitHubAppAuth(app_id="1", private_key=_rsa_private_pem(), client=client)
    assert auth.installation_token(42) == "tok_123"
    method, url, sent_headers = client.calls[0]
    assert method == "post"
    assert url == "https://api.github.com/app/installations/42/access_tokens"

def test_auth_installation_token_missing_raises() -> None:
    client = _FakeGitHubClient(_FakeGitHubResponse({}))
    auth = GitHubAppAuth(app_id="1", private_key=_rsa_private_pem(), client=client)
    with pytest.raises(RuntimeError):
        auth.installation_token(42)

def test_auth_http_errors_propagate() -> None:
    client = _FakeGitHubClient(_FakeGitHubResponse(error=httpx.HTTPError("boom")))
    auth = GitHubAppAuth(app_id="1", private_key=_rsa_private_pem(), client=client)
    with pytest.raises(httpx.HTTPError):
        auth.installation_details(42)

# ---------------------------------------------------------------------------
# Install-state signing and install URL
# ---------------------------------------------------------------------------

def test_install_state_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "statesecret")
    state = _issue_install_state()
    assert _verify_install_state(state) is True
    assert len(state.split(".")) == 3

def test_install_state_rejects_tampered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "statesecret")
    state = _issue_install_state()
    assert _verify_install_state(state + "x") is False
    assert _verify_install_state("not-a-state") is False

def test_install_state_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "statesecret")
    state = _issue_install_state()
    future = time.time() + _INSTALL_STATE_TTL_SECONDS + 5
    monkeypatch.setattr("app.github_app.time.time", lambda: future)
    assert _verify_install_state(state) is False

def test_install_state_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", raising=False)
    with pytest.raises(PermissionError):
        _issue_install_state()
    assert _verify_install_state("1.2.3") is False

def test_install_url_builds_signed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_SLUG", "acme-app")
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "statesecret")
    url = _install_url()
    assert url is not None
    parsed = urlparse(url)
    assert parsed.netloc == "github.com"
    assert parsed.path == "/apps/acme-app/installations/new"
    assert "state" in parse_qs(parsed.query)

def test_install_url_none_without_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SONAR_GITHUB_APP_SLUG", raising=False)
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "statesecret")
    assert _install_url() is None

# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def test_verify_signature_accepts_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "whsec")
    body = b'{"hello":"world"}'
    _verify_signature(body, _signed("whsec", body))

def test_verify_signature_rejects_bad_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "whsec")
    body = b'{"hello":"world"}'
    with pytest.raises(HTTPException) as missing:
        _verify_signature(body, None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as prefix:
        _verify_signature(body, "md5=abc")
    assert prefix.value.status_code == 401
    with pytest.raises(HTTPException) as mismatch:
        _verify_signature(body, _signed("other", body))
    assert mismatch.value.status_code == 401

def test_verify_signature_requires_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        _verify_signature(b"{}", "sha256=abc")
    assert exc.value.status_code == 503

# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

