"""Tests for the database-backed user account store (SqlUserStore)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import oauth
from app.main import app
from app.models.user import users  # noqa: F401 - registers table on metadata
from app.oauth import (
    OAuthUser,
    OAuthUserStore,
    new_state,
    set_oauth_transport,
    set_oauth_user_store,
)
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.repositories import SqlUserStore
from app.persistence.schema import metadata


@pytest.fixture
def store(tmp_path: Path) -> Generator[SqlUserStore, None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}")
    metadata.create_all(engine)
    yield SqlUserStore(engine, LocalDevelopmentEncryptionProvider(b"k" * 32))
    engine.dispose()


def _github_upsert(store: SqlUserStore, **kwargs: object) -> OAuthUser:
    defaults: dict[str, object] = {
        "provider": "github",
        "provider_user_id": "gh-1",
        "name": "Mike S",
        "email": "mike@example.com",
        "avatar_url": "https://img/x.png",
        "github_access_token": "gh-token-1",
        "github_username": "mikes",
    }
    defaults.update(kwargs)
    return store.upsert(**defaults)  # type: ignore[arg-type]


class TestUpsert:
    def test_create_github_user(self, store: SqlUserStore) -> None:
        user = _github_upsert(store)
        assert user.id
        assert user.provider == "github"
        assert user.github_id == "gh-1"
        assert user.github_username == "mikes"
        assert user.google_sub == ""
        assert user.email == "mike@example.com"
        assert user.plan == "free"
        assert user.status == "active"
        assert user.is_admin is False
        assert user.last_login_at
        assert user.created_at
        assert user.updated_at

        loaded = store.get(user.id)
        assert loaded is not None
        assert loaded.id == user.id
        # Token round-trips through encryption.
        assert loaded.github_access_token == "gh-token-1"

    def test_update_existing_identity(self, store: SqlUserStore) -> None:
        user = _github_upsert(store)
        updated = _github_upsert(store, name="Mike Smith", github_access_token="gh-token-2")
        assert updated.id == user.id
        assert updated.name == "Mike Smith"
        assert updated.github_access_token == "gh-token-2"
        assert store.count() == 1

    def test_cross_provider_email_linking(self, store: SqlUserStore) -> None:
        github_user = _github_upsert(store)
        google_user = store.upsert(
            provider="google",
            provider_user_id="google-1",
            name="Mike S",
            email="MIKE@EXAMPLE.COM",  # case-insensitive match
            avatar_url="https://img/y.png",
        )
        # Same account: provider identity wins first, email merge second.
        assert google_user.id == github_user.id
        merged = store.get(github_user.id)
        assert merged is not None
        assert merged.github_id == "gh-1"
        assert merged.google_sub == "google-1"
        # GitHub token survives the Google sign-in.
        assert merged.github_access_token == "gh-token-1"
        assert store.count() == 1

    def test_email_normalized_on_write(self, store: SqlUserStore) -> None:
        _github_upsert(store, email="  Mike@Example.com  ")
        assert store.get_by_email("mike@example.com") is not None
        assert store.get_by_email("MIKE@example.com") is not None

    def test_blank_emails_do_not_collide(self, store: SqlUserStore) -> None:
        _github_upsert(store, email="")
        _github_upsert(store, provider_user_id="gh-2", email="")
        assert store.count() == 2
        assert store.get_by_email("") is None

    def test_google_upsert_stores_sub(self, store: SqlUserStore) -> None:
        user = store.upsert(
            provider="google",
            provider_user_id="google-9",
            name="Mike G",
            email="mike@gmail.com",
            avatar_url="https://img/y.png",
        )
        assert user.google_sub == "google-9"
        assert user.github_id == ""
        assert user.github_access_token == ""

    def test_token_encrypted_at_rest(self, store: SqlUserStore, tmp_path: Path) -> None:
        _github_upsert(store, github_access_token="super-secret-token")
        database = store.engine.url.database
        assert database is not None
        with sqlite3.connect(database) as connection:
            (ciphertext,) = connection.execute(
                "select github_token_ciphertext from users"
            ).fetchone()
        assert ciphertext
        assert "super-secret-token" not in ciphertext


class TestAdmin:
    def test_set_status(self, store: SqlUserStore) -> None:
        user = _github_upsert(store)
        suspended = store.set_status(user.id, "suspended")
        assert suspended.status == "suspended"
        assert store.get(user.id) is not None
        active = store.set_status(user.id, "active")
        assert active.status == "active"

    def test_set_status_rejects_unknown(self, store: SqlUserStore) -> None:
        user = _github_upsert(store)
        with pytest.raises(ValueError):
            store.set_status(user.id, "banned")

    def test_set_status_missing_user(self, store: SqlUserStore) -> None:
        with pytest.raises(LookupError):
            store.set_status("nope", "suspended")

    def test_set_admin(self, store: SqlUserStore) -> None:
        user = _github_upsert(store)
        admin = store.set_admin(user.id, True)
        assert admin.is_admin is True
        assert store.set_admin(user.id, False).is_admin is False

    def test_set_plan(self, store: SqlUserStore) -> None:
        user = _github_upsert(store)
        assert store.set_plan(user.id, "pro").plan == "pro"


def _write_legacy_json(path: Path) -> bytes:
    records = [
        {
            "id": "user-gh",
            "provider": "github",
            "provider_user_id": "gh-1",
            "name": "Mike S",
            "email": "mike@example.com",
            "avatar_url": "https://img/x.png",
            "github_access_token": "gh-legacy-token",
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        },
        {
            "id": "user-goog",
            "provider": "google",
            "provider_user_id": "google-1",
            "name": "Mike S",
            "email": "MIKE@EXAMPLE.COM",
            "avatar_url": "https://img/y.png",
            "github_access_token": "",
            "created_at": "2026-09-02T00:00:00Z",
            "updated_at": "2026-09-02T00:00:00Z",
        },
    ]
    payload = json.dumps(records, indent=2).encode("utf-8")
    path.write_bytes(payload)
    return payload


class TestLegacyImport:
    def test_import_merges_and_preserves_json(self, store: SqlUserStore, tmp_path: Path) -> None:
        json_path = tmp_path / "oauth-users.json"
        original = _write_legacy_json(json_path)

        imported = store.import_legacy_json(json_path)
        assert imported == 1
        assert store.count() == 1

        user = store.get("user-gh")
        assert user is not None
        assert user.github_id == "gh-1"
        assert user.google_sub == "google-1"
        assert user.github_access_token == "gh-legacy-token"

        # Source file is untouched.
        assert json_path.read_bytes() == original

        # A second import is a no-op once the table is populated.
        assert store.import_legacy_json(json_path) == 0

    def test_import_skips_populated_table(self, store: SqlUserStore, tmp_path: Path) -> None:
        _github_upsert(store)
        json_path = tmp_path / "oauth-users.json"
        _write_legacy_json(json_path)
        assert store.import_legacy_json(json_path) == 0
        assert store.count() == 1

    def test_import_missing_file_is_noop(self, store: SqlUserStore, tmp_path: Path) -> None:
        assert store.import_legacy_json(tmp_path / "does-not-exist.json") == 0

    def test_import_uses_json_store_contract(self, store: SqlUserStore, tmp_path: Path) -> None:
        # Records written by OAuthUserStore itself round-trip through import.
        json_path = tmp_path / "oauth-users.json"
        legacy = OAuthUserStore(path=json_path)
        legacy.upsert(
            provider="github",
            provider_user_id="gh-7",
            name="Mike S",
            email="mike@example.com",
            avatar_url="https://img/x.png",
            github_access_token="gh-token",
            github_username="mikes",
        )
        assert store.import_legacy_json(json_path) == 1
        user = store.get_by_email("mike@example.com")
        assert user is not None
        assert user.github_username == "mikes"


class TestOAuthCallbacksWithDb:
    """OAuth callbacks against the database-backed user store."""

    @pytest.fixture
    def db_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: SqlUserStore
    ) -> Generator[SqlUserStore, None, None]:
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "gh-client-id")
        monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "gh-client-secret")
        monkeypatch.setenv("SONAR_PUBLIC_URL", "http://127.0.0.1:8000")
        monkeypatch.setenv("SONAR_SESSION_SECRET", "test-secret")
        previous = oauth.get_oauth_user_store()
        set_oauth_user_store(store)
        monkeypatch.setattr(oauth, "_secret_warning_emitted", True)

        def fake_post(
            url: str, body: dict[str, Any], headers: dict[str, str]
        ) -> tuple[int, dict[str, Any]]:
            if "github.com/login/oauth/access_token" in url:
                return 200, {"access_token": "gh-oauth-token"}
            raise AssertionError(f"unexpected POST {url}")

        def fake_get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
            if "api.github.com/user" in url and "/emails" not in url:
                return 200, {
                    "id": 4242,
                    "login": "mikes",
                    "name": "Mike S",
                    "email": "mike@example.com",
                    "avatar_url": "https://img/x.png",
                }
            if "api.github.com/user/emails" in url:
                return 200, [{"email": "mike@example.com", "primary": True, "verified": True}]
            raise AssertionError(f"unexpected GET {url}")

        previous_post, previous_get = oauth._http_post, oauth._http_get
        set_oauth_transport(fake_post, fake_get)
        yield store
        set_oauth_transport(previous_post, previous_get)
        set_oauth_user_store(previous)

    def _callback(self, client: TestClient) -> Any:
        state = new_state("test-secret")
        return client.get(
            "/api/auth/github/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )

    def test_callback_creates_db_user(self, db_env: SqlUserStore) -> None:
        client = TestClient(app)
        response = self._callback(client)
        assert response.status_code == 302
        assert response.headers["location"] == "/app"

        assert db_env.count() == 1
        user = db_env.get_by_email("mike@example.com")
        assert user is not None
        assert user.github_username == "mikes"
        assert user.github_access_token == "gh-oauth-token"
        assert user.last_login_at

        # The issued session works against the DB store.
        session = response.headers["set-cookie"].split("sonar_session=")[1].split(";")[0]
        client.cookies.set("sonar_session", session)
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "mike@example.com"

    def test_suspended_user_cannot_log_in(self, db_env: SqlUserStore) -> None:
        db_env.set_status(
            _github_upsert(db_env, provider_user_id="4242", email="mike@example.com").id,
            "suspended",
        )
        client = TestClient(app)
        response = self._callback(client)
        assert response.status_code == 403
        assert "suspended" in response.json()["detail"]

    def test_suspended_session_rejected(self, db_env: SqlUserStore) -> None:
        client = TestClient(app)
        response = self._callback(client)
        session = response.headers["set-cookie"].split("sonar_session=")[1].split(";")[0]
        client.cookies.set("sonar_session", session)
        assert client.get("/api/auth/me").status_code == 200

        user = db_env.get_by_email("mike@example.com")
        assert user is not None
        db_env.set_status(user.id, "suspended")
        assert client.get("/api/auth/me").status_code == 401
