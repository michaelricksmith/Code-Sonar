"""Tests for the GitHub + Google OAuth Authorization Code flow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import oauth
from app.main import app
from app.oauth import (
    OAuthUserStore,
    new_state,
    set_oauth_transport,
    set_oauth_user_store,
)

_TEST_SECRET = "test-session-secret"


@pytest.fixture
def oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "gh-client-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "gh-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv("SONAR_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SECRET)


@pytest.fixture
def oauth_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OAuthUserStore:
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth.get_oauth_user_store()
    set_oauth_user_store(store)
    monkeypatch.setattr(oauth, "_secret_warning_emitted", True)
    yield store
    set_oauth_user_store(previous)


@pytest.fixture
def oauth_http(oauth_env: None) -> Any:
    calls: dict[str, Any] = {}

    def fake_post(url: str, body: dict[str, Any], headers: dict[str, str]):
        calls["post_url"] = url
        if "github.com/login/oauth/access_token" in url:
            assert body["client_id"] == "gh-client-id"
            assert "client_secret" not in body or body  # secret sent server-side only
            return 200, {"access_token": "gh-oauth-token"}
        if "oauth2.googleapis.com/token" in url:
            assert body["client_id"] == "google-client-id"
            return 200, {"access_token": "google-oauth-token"}
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, headers: dict[str, str]):
        calls["get_url"] = url
        if url == "https://api.github.com/user":
            assert headers["Authorization"] == "Bearer gh-oauth-token"
            return 200, {
                "id": 4242,
                "login": "mike",
                "name": "Mike S",
                "email": "mike@example.com",
                "avatar_url": "https://avatars/x.png",
            }
        if "api.github.com/user/repos" in url:
            assert headers["Authorization"] == "Bearer gh-oauth-token"
            return 200, {
                "_items": [
                    {
                        "id": 7,
                        "full_name": "mike/demo",
                        "name": "demo",
                        "pushed_at": "2026-09-01T00:00:00Z",
                        "private": False,
                        "default_branch": "main",
                    }
                ]
            }
        if "googleapis.com/oauth2/v3/userinfo" in url:
            assert headers["Authorization"] == "Bearer google-oauth-token"
            return 200, {
                "sub": "google-123",
                "name": "Mike G",
                "email": "mike@gmail.com",
                "picture": "https://img/y.png",
            }
        raise AssertionError(f"unexpected GET {url}")

    previous_post, previous_get = oauth._http_post, oauth._http_get
    set_oauth_transport(fake_post, fake_get)
    yield calls
    set_oauth_transport(previous_post, previous_get)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _session_cookie_value(response: Any) -> str:
    set_cookie = response.headers.get("set-cookie", "")
    match = re.search(r"sonar_session=([^;]+)", set_cookie)
    assert match, f"sonar_session cookie missing in: {set_cookie!r}"
    return match.group(1)


class TestGitHubLogin:
    def test_login_redirects_to_github(self, client, oauth_env):
        response = client.get("/api/auth/github/login", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://github.com/login/oauth/authorize")
        assert "client_id=gh-client-id" in location
        assert "state=" in location
        assert "redirect_uri=" in location

    def test_login_unconfigured_returns_honest_error(
        self, client, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SECRET)
        response = client.get("/api/auth/github/login", follow_redirects=False)
        assert response.status_code == 503
        assert "GITHUB_OAUTH_CLIENT_ID" in response.json()["detail"]


class TestGitHubCallback:
    def test_callback_creates_user_sets_cookie_and_redirects(
        self, client, oauth_http, oauth_store
    ):
        state = new_state(_TEST_SECRET)
        response = client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/app"

        set_cookie = response.headers["set-cookie"]
        assert "sonar_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=Lax" in set_cookie or "samesite=lax" in set_cookie.lower()

        stored = oauth_store.get(oauth_store._load()[0].id)
        assert stored is not None
        assert stored.provider == "github"
        assert stored.name == "Mike S"
        assert stored.email == "mike@example.com"
        assert stored.github_access_token == "gh-oauth-token"

    def test_callback_rejects_bad_state(self, client, oauth_http, oauth_store):
        response = client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": "forged"},
            follow_redirects=False,
        )
        assert response.status_code == 400

    def test_callback_requires_code(self, client, oauth_http, oauth_store):
        state = new_state(_TEST_SECRET)
        response = client.get(
            "/api/auth/github/callback",
            params={"state": state},
            follow_redirects=False,
        )
        assert response.status_code == 400


class TestGoogleFlow:
    def test_google_login_redirects(self, client, oauth_env):
        response = client.get("/api/auth/google/login", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "client_id=google-client-id" in location

    def test_google_callback_creates_user(self, client, oauth_http, oauth_store):
        state = new_state(_TEST_SECRET)
        response = client.get(
            "/api/auth/google/callback",
            params={"code": "google-code", "state": state},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/app"
        stored = oauth_store._load()[0]
        assert stored.provider == "google"
        assert stored.name == "Mike G"
        assert stored.email == "mike@gmail.com"
        assert stored.github_access_token == ""


class TestSession:
    def test_me_returns_public_profile(self, client, oauth_http, oauth_store):
        state = new_state(_TEST_SECRET)
        callback = client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
        cookie = _session_cookie_value(callback)
        response = client.get(
            "/api/auth/me", headers={"Cookie": f"sonar_session={cookie}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "github"
        assert data["name"] == "Mike S"
        assert data["email"] == "mike@example.com"
        assert data["avatar_url"] == "https://avatars/x.png"
        assert "id" in data
        assert "github_access_token" not in str(data)

    def test_me_unauthenticated_is_401(self, client, oauth_env):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_tampered_cookie_is_401(self, client, oauth_env):
        response = client.get(
            "/api/auth/me", headers={"Cookie": "sonar_session=tampered.value.here"}
        )
        assert response.status_code == 401

    def test_logout_clears_cookie(self, client, oauth_env):
        response = client.post("/api/auth/logout")
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "sonar_session=" in set_cookie


class TestRepos:
    def test_repos_returns_mapped_list(self, client, oauth_http, oauth_store):
        state = new_state(_TEST_SECRET)
        callback = client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
        cookie = _session_cookie_value(callback)
        response = client.get(
            "/api/auth/repos", headers={"Cookie": f"sonar_session={cookie}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        repo = data["repos"][0]
        assert repo == {
            "id": 7,
            "full_name": "mike/demo",
            "name": "demo",
            "pushed_at": "2026-09-01T00:00:00Z",
            "private": False,
            "default_branch": "main",
        }

    def test_repos_unauthenticated_is_401(self, client, oauth_env):
        assert client.get("/api/auth/repos").status_code == 401

    def test_repos_without_github_link_is_409(self, client, oauth_http, oauth_store):
        state = new_state(_TEST_SECRET)
        callback = client.get(
            "/api/auth/google/callback",
            params={"code": "google-code", "state": state},
            follow_redirects=False,
        )
        cookie = _session_cookie_value(callback)
        response = client.get(
            "/api/auth/repos", headers={"Cookie": f"sonar_session={cookie}"}
        )
        assert response.status_code == 409
