"""Session-cookie auth as a first-class production auth path.

The API boundary middleware must accept a valid signed ``sonar_session``
cookie the same way it accepts a Bearer token — with no
``CODESONAR_LOCAL_DEV=1`` dev flag required for hosted operation.
"""

from __future__ import annotations

import time
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from app import oauth as oauth_module
from app.main import app
from app.oauth import OAuthUserStore, new_session_token
from app.security.runtime import validate_runtime_security_config

_TEST_SESSION_SECRET = "test-session-secret-0123456789abcdef"


@pytest.fixture
def session_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hosted posture: no dev flag, no Bearer credentials, session secret set."""
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SESSION_SECRET)
    monkeypatch.delenv("CODESONAR_API_TOKEN", raising=False)
    monkeypatch.delenv("CODESONAR_API_TENANT_TOKENS", raising=False)


@pytest.fixture
def session_user(tmp_path: Path):
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth_module.get_oauth_user_store()
    oauth_module.set_oauth_user_store(store)
    try:
        user = store.upsert(
            provider="github",
            provider_user_id="4242",
            name="Mike S",
            email="mike@example.com",
            avatar_url="",
        )
        yield user
    finally:
        oauth_module.set_oauth_user_store(previous)


@pytest.fixture
def authed_client(session_auth_env: None, session_user) -> TestClient:
    client = TestClient(app)
    client.cookies.set(
        "sonar_session", new_session_token(session_user.id, _TEST_SESSION_SECRET)
    )
    return client


def test_session_cookie_grants_api_access_without_dev_flag(
    authed_client: TestClient,
) -> None:
    assert authed_client.get("/api/analyzers").status_code == 200


def test_anonymous_request_rejected_without_dev_flag(
    session_auth_env: None, session_user
) -> None:
    assert TestClient(app).get("/api/analyzers").status_code == 401


def test_session_cookie_accepted_alongside_bearer_config(
    monkeypatch: pytest.MonkeyPatch, session_auth_env: None, session_user
) -> None:
    monkeypatch.setenv("CODESONAR_API_TOKEN", "server-token")
    client = TestClient(app)
    client.cookies.set(
        "sonar_session", new_session_token(session_user.id, _TEST_SESSION_SECRET)
    )
    # Valid session cookie works even when Bearer credentials are configured
    # and no Authorization header is sent.
    assert client.get("/api/analyzers").status_code == 200
    # And the Bearer path is unchanged.
    assert (
        client.get(
            "/api/analyzers", headers={"Authorization": "Bearer server-token"}
        ).status_code
        == 200
    )
    # Neither credential -> 401.
    assert TestClient(app).get("/api/analyzers").status_code == 401


def test_tampered_session_cookie_rejected(
    session_auth_env: None, session_user
) -> None:
    client = TestClient(app)
    client.cookies.set(
        "sonar_session", new_session_token(session_user.id, "wrong-secret")
    )
    assert client.get("/api/analyzers").status_code == 401


def test_expired_session_cookie_rejected(
    session_auth_env: None, session_user
) -> None:
    now = int(time.time())
    expired = jwt.encode(
        {"sub": session_user.id, "iat": now - 7200, "exp": now - 3600},
        _TEST_SESSION_SECRET,
        algorithm="HS256",
    )
    client = TestClient(app)
    client.cookies.set("sonar_session", expired)
    assert client.get("/api/analyzers").status_code == 401


def test_session_cookie_for_unknown_user_rejected(session_auth_env: None) -> None:
    client = TestClient(app)
    client.cookies.set(
        "sonar_session", new_session_token("no-such-user", _TEST_SESSION_SECRET)
    )
    assert client.get("/api/analyzers").status_code == 401


def test_local_dev_bypass_unchanged_without_any_credential() -> None:
    """CODESONAR_LOCAL_DEV=1 keeps its unauthenticated local ergonomics."""
    # The autouse conftest fixture already sets CODESONAR_LOCAL_DEV=1 with no
    # API token configured.
    assert TestClient(app).get("/api/analyzers").status_code == 200


def test_oauth_handshake_reachable_anonymously(
    monkeypatch: pytest.MonkeyPatch, session_auth_env: None
) -> None:
    """A signed-out user must be able to START sign-in (no 401 on login)."""
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "gh-client-id")
    client = TestClient(app)
    response = client.get("/api/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://github.com/login/oauth/authorize"
    )
    # Google is not configured here -> honest 503, not 401.
    assert client.get("/api/auth/google/login").status_code == 503


def test_startup_fails_closed_without_any_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    monkeypatch.setenv("CODESONAR_HOST", "0.0.0.0")
    monkeypatch.delenv("CODESONAR_API_TOKEN", raising=False)
    monkeypatch.delenv("CODESONAR_API_TENANT_TOKENS", raising=False)
    monkeypatch.delenv("SONAR_SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CODESONAR_API_TOKEN is required"):
        validate_runtime_security_config()
    # An explicitly configured session secret is a valid production auth path.
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SESSION_SECRET)
    validate_runtime_security_config()


def test_session_cookie_scopes_me_endpoint(
    authed_client: TestClient, session_user
) -> None:
    response = authed_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["id"] == session_user.id
