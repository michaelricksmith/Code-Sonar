"""Tests for GitHub account linking (connect/disconnect without switching logins)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import oauth
from app.main import app
from app.oauth import (
    OAuthUserStore,
    new_github_connect_state,
    new_session_token,
    new_state,
    parse_github_connect_state,
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
    def fake_post(url: str, body: dict[str, Any], headers: dict[str, str]):
        if "github.com/login/oauth/access_token" in url:
            return 200, {"access_token": "gh-oauth-token"}
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, headers: dict[str, str]):
        if url == "https://api.github.com/user":
            assert headers["Authorization"] == "Bearer gh-oauth-token"
            return 200, {
                "id": 4242,
                "login": "mike",
                "name": "Mike S",
                "email": "mike@example.com",
                "avatar_url": "https://avatars/x.png",
            }
        raise AssertionError(f"unexpected GET {url}")

    previous_post, previous_get = oauth._http_post, oauth._http_get
    oauth.set_oauth_transport(fake_post, fake_get)
    yield None
    oauth.set_oauth_transport(previous_post, previous_get)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _google_user(oauth_store: OAuthUserStore, provider_user_id: str = "google-123"):
    return oauth_store.upsert(
        provider="google",
        provider_user_id=provider_user_id,
        name="Mike G",
        email="mike@gmail.com",
        avatar_url="https://img/y.png",
        github_access_token="",
        github_username="",
    )


def _signed_in(client: TestClient, user_id: str) -> None:
    client.cookies.set("sonar_session", new_session_token(user_id, _TEST_SECRET))


class TestConnectState:
    def test_round_trip_returns_user_id(self):
        state = new_github_connect_state(_TEST_SECRET, "user-abc")
        assert parse_github_connect_state(state, _TEST_SECRET) == "user-abc"

    def test_login_state_is_not_a_connect_state(self):
        assert parse_github_connect_state(new_state(_TEST_SECRET), _TEST_SECRET) is None

    def test_tampered_state_rejected(self):
        state = new_github_connect_state(_TEST_SECRET, "user-abc")
        payload, issued_at, _digest = state.rsplit(".", 2)
        tampered = f"{payload}.{issued_at}.{'0' * 64}"
        assert parse_github_connect_state(tampered, _TEST_SECRET) is None

    def test_expired_state_rejected(self):
        payload, _, _digest = new_github_connect_state(_TEST_SECRET, "user-abc").rsplit(".", 2)
        old_issued = str(int(time.time()) - 20 * 60)
        expired = oauth._sign_state(f"{payload}.{old_issued}", _TEST_SECRET)
        assert parse_github_connect_state(expired, _TEST_SECRET) is None

    def test_empty_state_rejected(self):
        assert parse_github_connect_state(None, _TEST_SECRET) is None
        assert parse_github_connect_state("", _TEST_SECRET) is None


class TestConnectEndpoint:
    def test_requires_login(self, client, oauth_env, oauth_store):
        response = client.get("/api/auth/github/connect", follow_redirects=False)
        assert response.status_code == 401

    def test_redirects_to_github_with_connect_state(self, client, oauth_env, oauth_store):
        user = _google_user(oauth_store)
        _signed_in(client, user.id)
        response = client.get("/api/auth/github/connect", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://github.com/login/oauth/authorize")
        query = parse_qs(urlparse(location).query)
        assert query["client_id"] == ["gh-client-id"]
        assert query["scope"] == ["read:user repo"]
        state = query["state"][0]
        assert parse_github_connect_state(state, _TEST_SECRET) == user.id

    def test_unconfigured_returns_honest_error(
        self, client, oauth_store, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
        monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SECRET)
        user = _google_user(oauth_store)
        _signed_in(client, user.id)
        response = client.get("/api/auth/github/connect", follow_redirects=False)
        assert response.status_code == 503


class TestConnectCallback:
    def _callback(self, client, state):
        return client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )

    def test_links_github_to_existing_user(self, client, oauth_env, oauth_http, oauth_store):
        user = _google_user(oauth_store)
        _signed_in(client, user.id)
        state = new_github_connect_state(_TEST_SECRET, user.id)

        response = self._callback(client, state)

        assert response.status_code == 302
        assert response.headers["location"] == "/app"
        # No new session minted: the callback must not set a session cookie.
        assert "sonar_session" not in response.headers.get("set-cookie", "")
        # Exactly one user record, now carrying the GitHub credential.
        assert len(oauth_store._load()) == 1
        stored = oauth_store.get(user.id)
        assert stored is not None
        assert stored.provider == "google"
        assert stored.github_access_token == "gh-oauth-token"
        assert stored.github_username == "mike"
        assert stored.github_id == "4242"
        # Plan and flags untouched.
        assert stored.plan == user.plan
        assert stored.is_admin == user.is_admin
        assert stored.is_staff == user.is_staff

    def test_rejects_session_mismatch(self, client, oauth_env, oauth_http, oauth_store):
        user_a = _google_user(oauth_store, provider_user_id="google-aaa")
        user_b = _google_user(oauth_store, provider_user_id="google-bbb")
        _signed_in(client, user_b.id)
        state = new_github_connect_state(_TEST_SECRET, user_a.id)

        response = self._callback(client, state)

        assert response.status_code == 403
        assert oauth_store.get(user_b.id).github_access_token == ""

    def test_requires_login(self, client, oauth_env, oauth_http, oauth_store):
        user = _google_user(oauth_store)
        state = new_github_connect_state(_TEST_SECRET, user.id)

        response = self._callback(client, state)

        assert response.status_code == 401

    def test_login_flow_unaffected(self, client, oauth_env, oauth_http, oauth_store):
        # A plain login state still creates a fresh GitHub user + session.
        state = new_state(_TEST_SECRET)
        response = self._callback(client, state)
        assert response.status_code == 302
        assert response.headers["location"] == "/app"
        assert "sonar_session" in response.headers.get("set-cookie", "")
        stored = oauth_store._load()[0]
        assert stored.provider == "github"


class TestConnectConflict:
    def _github_user(self, oauth_store: OAuthUserStore):
        # User B signed in with GitHub: the identity (github_id "4242")
        # already belongs to B. A distinct email keeps the accounts separate
        # (the SQL store merges cross-provider duplicates by email).
        return oauth_store.upsert(
            provider="github",
            provider_user_id="4242",
            name="Mike GH",
            email="mikegh@example.com",
            avatar_url="https://img/z.png",
            github_access_token="old-token",
            github_username="mike",
        )

    def test_identity_owned_by_another_account_returns_409_not_500(
        self, client, oauth_env, oauth_http, oauth_store
    ):
        user_b = self._github_user(oauth_store)
        user_a = _google_user(oauth_store)
        _signed_in(client, user_a.id)
        state = new_github_connect_state(_TEST_SECRET, user_a.id)

        response = client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )

        assert response.status_code == 409
        assert "already linked" in response.json()["detail"]
        # Neither account may be modified by the failed link attempt.
        stored_a = oauth_store.get(user_a.id)
        assert stored_a is not None
        assert stored_a.github_id == ""
        assert stored_a.github_access_token == ""
        stored_b = oauth_store.get(user_b.id)
        assert stored_b is not None
        assert stored_b.github_id == "4242"
        assert stored_b.github_access_token == "old-token"

    def test_relink_same_identity_to_owner_is_idempotent(
        self, client, oauth_env, oauth_http, oauth_store
    ):
        user = _google_user(oauth_store)
        _signed_in(client, user.id)

        for _ in range(2):
            state = new_github_connect_state(_TEST_SECRET, user.id)
            response = client.get(
                "/api/auth/github/callback",
                params={"code": "auth-code", "state": state},
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert response.headers["location"] == "/app"

        stored = oauth_store.get(user.id)
        assert stored is not None
        assert stored.github_id == "4242"
        assert stored.github_username == "mike"
        assert len(oauth_store._load()) == 1


class TestDisconnect:
    def test_requires_login(self, client, oauth_env, oauth_store):
        response = client.post("/api/auth/github/disconnect")
        assert response.status_code == 401

    def test_clears_github_credentials(self, client, oauth_env, oauth_store):
        user = _google_user(oauth_store)
        linked = oauth_store.link_github(
            user.id,
            github_id="4242",
            github_username="mike",
            github_access_token="gh-oauth-token",
        )
        assert linked is not None and linked.github_access_token == "gh-oauth-token"
        _signed_in(client, user.id)

        response = client.post("/api/auth/github/disconnect")

        assert response.status_code == 200
        assert response.json() == {"status": "disconnected"}
        stored = oauth_store.get(user.id)
        assert stored is not None
        assert stored.github_access_token == ""
        assert stored.github_username == ""
        assert stored.github_id == ""
