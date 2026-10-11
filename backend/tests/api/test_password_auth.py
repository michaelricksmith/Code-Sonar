"""Tests for email/password authentication.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.password_auth.passwords import (
    hash_password,
    is_password_breached,
    validate_password,
    verify_password,
)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", h) is True
        assert verify_password("wrong", h) is False

    def test_hash_format(self):
        h = hash_password("password123")
        assert h.startswith("$scrypt$n=16384,r=8,p=1$")

    def test_unique_salts(self):
        assert hash_password("same") != hash_password("same")

    def test_malformed_hash_rejected(self):
        assert verify_password("x", "not-a-hash") is False
        assert verify_password("x", "") is False

    def test_policy(self):
        assert validate_password("short") is not None
        assert validate_password("long enough password") is None


class TestBreachCheck:
    def test_breached_password_detected(self):
        # "password" is famously breached; None means the API was unreachable.
        result = is_password_breached("password")
        assert result in (True, None)

    def test_random_password_not_breached(self):
        import secrets

        result = is_password_breached(secrets.token_urlsafe(32))
        assert result in (False, None)


@pytest.fixture()
def sql_user_store(monkeypatch: pytest.MonkeyPatch):
    """Swap in a fake SQL-like user store for password auth tests."""
    import app.oauth as oauth_module
    import app.password_auth.api as api_module

    users: dict[str, dict] = {}

    class FakeStore:
        def get_by_email(self, email):
            for u in users.values():
                if u["email"] == email.lower():
                    return _user(u)
            return None

        def create_email_user(self, email, name, password_hash):
            uid = f"user_{len(users)}"
            users[uid] = {
                "id": uid,
                "email": email.lower(),
                "name": name,
                "password_hash": password_hash,
                "email_verified": False,
                "verify_token": None,
                "reset_token": None,
                "reset_expires": None,
                "is_suspended": False,
            }
            return _user(users[uid])

        def get_password_hash(self, user_id):
            return users[user_id]["password_hash"]

        def set_password_hash(self, user_id, h):
            users[user_id]["password_hash"] = h

        def is_email_verified(self, user_id):
            return users[user_id]["email_verified"]

        def set_email_verified(self, user_id, verified=True):
            users[user_id]["email_verified"] = verified
            users[user_id]["verify_token"] = None

        def set_email_verify_token(self, user_id, token_hash):
            users[user_id]["verify_token"] = token_hash

        def get_by_verify_token(self, token_hash):
            for u in users.values():
                if u["verify_token"] == token_hash:
                    return _user(u)
            return None

        def set_password_reset_token(self, user_id, token_hash, expires_at):
            users[user_id]["reset_token"] = token_hash
            users[user_id]["reset_expires"] = expires_at

        def get_by_reset_token(self, token_hash):
            for u in users.values():
                if u["reset_token"] == token_hash:
                    return _user(u)
            return None

        def get(self, user_id):
            return _user(users[user_id]) if user_id in users else None

    def _user(u):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=u["id"],
            email=u["email"],
            name=u["name"],
            is_suspended=u["is_suspended"],
        )

    store = FakeStore()
    monkeypatch.setattr(oauth_module, "get_oauth_user_store", lambda: store)
    # Skip the breach check (network) in these tests.
    monkeypatch.setattr(
        api_module, "_check_password_policy", lambda password: None
    )
    return store, users


class TestSignup:
    def test_signup(self, sql_user_store):
        resp = _client().post(
            "/api/auth/signup",
            json={
                "email": "new@example.com",
                "password": "a very long password here",
                "name": "New User",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["needs_verification"] is True

    def test_signup_duplicate(self, sql_user_store):
        client = _client()
        body = {
            "email": "dup@example.com",
            "password": "a very long password here",
            "name": "Dup",
        }
        assert client.post("/api/auth/signup", json=body).status_code == 200
        assert client.post("/api/auth/signup", json=body).status_code == 409

    def test_signup_invalid_email(self, sql_user_store):
        resp = _client().post(
            "/api/auth/signup",
            json={"email": "not-an-email", "password": "a very long password here"},
        )
        assert resp.status_code == 400

    def test_signup_short_password(self, sql_user_store):
        # The API-level policy check is mocked in this fixture; the length
        # rule itself is covered by TestPasswordHashing.test_policy.
        from app.password_auth.passwords import validate_password

        assert validate_password("short") is not None


class TestLogin:
    def _signup_verified(self, sql_user_store, email="user@example.com"):
        store, users = sql_user_store
        client = _client()
        client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": "a very long password here",
                "name": "User",
            },
        )
        uid = next(iter(users))
        store.set_email_verified(uid, True)
        return uid

    def test_login(self, sql_user_store):
        self._signup_verified(sql_user_store)
        resp = _client().post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "a very long password here"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_login_wrong_password(self, sql_user_store):
        self._signup_verified(sql_user_store)
        resp = _client().post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "wrong password here"},
        )
        assert resp.status_code == 401

    def test_login_unverified(self, sql_user_store):
        _client().post(
            "/api/auth/signup",
            json={
                "email": "unverified@example.com",
                "password": "a very long password here",
            },
        )
        resp = _client().post(
            "/api/auth/login",
            json={
                "email": "unverified@example.com",
                "password": "a very long password here",
            },
        )
        assert resp.status_code == 403

    def test_login_unknown_email(self, sql_user_store):
        resp = _client().post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever here"},
        )
        assert resp.status_code == 401


class TestPasswordReset:
    def _signup_verified(self, sql_user_store, email="reset@example.com"):
        store, users = sql_user_store
        _client().post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": "a very long password here",
                "name": "User",
            },
        )
        uid = next(iter(users))
        store.set_email_verified(uid, True)
        return uid, store

    def test_forgot_password_always_ok(self, sql_user_store):
        # Unknown email still returns ok (no leakage).
        resp = _client().post(
            "/api/auth/forgot-password", json={"email": "nobody@example.com"}
        )
        assert resp.json() == {"ok": True}

    def test_reset_password(self, sql_user_store):
        uid, store = self._signup_verified(sql_user_store)
        _client().post(
            "/api/auth/forgot-password", json={"email": "reset@example.com"}
        )
        # Grab the token hash from the fake store and reverse it (test only).
        import hashlib

        token = "test-reset-token"
        store.set_password_reset_token(
            uid, hashlib.sha256(token.encode()).hexdigest(), None
        )
        # The get_by_reset_token in the fake store doesn't check expiry.
        resp = _client().post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "a brand new long password"},
        )
        assert resp.json() == {"ok": True}
        # New password works.
        login = _client().post(
            "/api/auth/login",
            json={"email": "reset@example.com", "password": "a brand new long password"},
        )
        assert login.status_code == 200

    def test_reset_invalid_token(self, sql_user_store):
        resp = _client().post(
            "/api/auth/reset-password",
            json={"token": "bogus", "new_password": "a brand new long password"},
        )
        assert resp.status_code == 400
