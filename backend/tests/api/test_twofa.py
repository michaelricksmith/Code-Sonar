"""Tests for TOTP two-factor authentication.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.twofa import totp
from app.twofa.api import new_pending_token, verify_pending_token
from app.twofa.store import (
    InMemoryTwoFactorStore,
    get_two_factor_store,
    is_locked,
    set_two_factor_store,
    verify_login_code,
)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def isolated_twofa():
    original = get_two_factor_store()
    store = InMemoryTwoFactorStore()
    set_two_factor_store(store)
    try:
        yield store
    finally:
        set_two_factor_store(original)


@pytest.fixture(autouse=True)
def _signed_in_user(monkeypatch: pytest.MonkeyPatch):
    import app.oauth as oauth_module

    monkeypatch.setattr(
        oauth_module, "current_user", lambda r: SimpleNamespace(id="user-1")
    )
    monkeypatch.setattr(
        oauth_module,
        "get_oauth_user_store",
        lambda: SimpleNamespace(
            get=lambda uid: SimpleNamespace(
                id=uid, email="user@example.com", is_suspended=False
            )
        ),
    )


class TestTotp:
    def test_generate_and_verify(self):
        secret = totp.generate_secret()
        code = totp.totp_code(secret)
        assert totp.verify_code(secret, code) is True

    def test_wrong_code_rejected(self):
        secret = totp.generate_secret()
        assert totp.verify_code(secret, "000000") is False

    def test_malformed_code_rejected(self):
        secret = totp.generate_secret()
        assert totp.verify_code(secret, "abc") is False
        assert totp.verify_code(secret, "") is False

    def test_clock_skew_window(self):
        secret = totp.generate_secret()
        now = time.time()
        assert totp.verify_code(secret, totp.totp_code(secret, now - 30), now) is True
        assert totp.verify_code(secret, totp.totp_code(secret, now + 30), now) is True
        assert totp.verify_code(secret, totp.totp_code(secret, now - 90), now) is False

    def test_otpauth_uri(self):
        uri = totp.otpauth_uri("JBSWY3DPEHPK3PXP", "user@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "secret=JBSWY3DPEHPK3PXP" in uri

    def test_qr_svg(self):
        svg = totp.qr_svg(totp.otpauth_uri("JBSWY3DPEHPK3PXP", "u@e.c"))
        assert "<svg" in svg

    def test_backup_codes(self):
        codes = totp.generate_backup_codes()
        assert len(codes) == 8
        assert len(set(codes)) == 8
        h1 = totp.hash_backup_code(codes[0])
        assert h1 == totp.hash_backup_code(codes[0].lower())


class TestPendingToken:
    def test_round_trip(self):
        token = new_pending_token("user-1")
        assert verify_pending_token(token) == "user-1"

    def test_tampered_rejected(self):
        assert verify_pending_token("garbage") is None
        assert verify_pending_token(None) is None

    def test_wrong_purpose_rejected(self):
        import jwt

        from app.oauth import _session_secret

        token = jwt.encode(
            {"sub": "user-1", "purpose": "other"}, _session_secret(), algorithm="HS256"
        )
        assert verify_pending_token(token) is None


class TestEnrollment:
    def test_status_disabled_by_default(self, isolated_twofa):
        body = _client().get("/api/2fa/status").json()
        assert body["enabled"] is False

    def test_enroll_returns_qr(self, isolated_twofa):
        body = _client().post("/api/2fa/enroll").json()
        assert "otpauth_uri" in body
        assert "<svg" in body["qr_svg"]
        assert len(body["manual_entry_code"]) > 0

    def test_enroll_requires_sign_in(self, isolated_twofa, monkeypatch):
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        assert _client().post("/api/2fa/enroll").status_code == 401

    def test_confirm_enables(self, isolated_twofa):
        _client().post("/api/2fa/enroll")
        secret = isolated_twofa.get_secret("user-1")
        assert secret is not None
        body = _client().post(
            "/api/2fa/confirm", json={"code": totp.totp_code(secret)}
        ).json()
        assert body["enabled"] is True
        assert len(body["backup_codes"]) == 8
        assert _client().get("/api/2fa/status").json()["enabled"] is True

    def test_confirm_wrong_code(self, isolated_twofa):
        _client().post("/api/2fa/enroll")
        resp = _client().post("/api/2fa/confirm", json={"code": "000000"})
        assert resp.status_code == 400
        assert _client().get("/api/2fa/status").json()["enabled"] is False

    def test_confirm_without_enroll(self, isolated_twofa):
        assert (
            _client().post("/api/2fa/confirm", json={"code": "123456"}).status_code
            == 400
        )

    def test_enroll_when_already_enabled(self, isolated_twofa):
        _client().post("/api/2fa/enroll")
        secret = isolated_twofa.get_secret("user-1")
        _client().post("/api/2fa/confirm", json={"code": totp.totp_code(secret)})
        assert _client().post("/api/2fa/enroll").status_code == 409

    def test_disable(self, isolated_twofa):
        _client().post("/api/2fa/enroll")
        secret = isolated_twofa.get_secret("user-1")
        _client().post("/api/2fa/confirm", json={"code": totp.totp_code(secret)})
        body = _client().post(
            "/api/2fa/disable", json={"code": totp.totp_code(secret)}
        ).json()
        assert body["enabled"] is False
        assert _client().get("/api/2fa/status").json()["enabled"] is False

    def test_disable_wrong_code(self, isolated_twofa):
        _client().post("/api/2fa/enroll")
        secret = isolated_twofa.get_secret("user-1")
        _client().post("/api/2fa/confirm", json={"code": totp.totp_code(secret)})
        assert (
            _client().post("/api/2fa/disable", json={"code": "000000"}).status_code
            == 400
        )
        assert _client().get("/api/2fa/status").json()["enabled"] is True


class TestVerifyLogin:
    def _enable(self, store: InMemoryTwoFactorStore) -> str:
        secret = totp.generate_secret()
        store.save_pending("user-1", secret)
        store.enable("user-1", [totp.hash_backup_code("ABCD1234")])
        return secret

    def test_verify_login_totp(self, isolated_twofa):
        secret = self._enable(isolated_twofa)
        client = _client()
        client.cookies.set("sonar_2fa_pending", new_pending_token("user-1"))
        resp = client.post(
            "/api/2fa/verify-login", json={"code": totp.totp_code(secret)}
        )
        assert resp.status_code == 204

    def test_verify_login_backup_code(self, isolated_twofa):
        self._enable(isolated_twofa)
        client = _client()
        client.cookies.set("sonar_2fa_pending", new_pending_token("user-1"))
        resp = client.post("/api/2fa/verify-login", json={"code": "ABCD1234"})
        assert resp.status_code == 204
        # Backup codes are single-use.
        client.cookies.set("sonar_2fa_pending", new_pending_token("user-1"))
        assert (
            client.post("/api/2fa/verify-login", json={"code": "ABCD1234"}).status_code
            == 400
        )

    def test_verify_login_wrong_code(self, isolated_twofa):
        self._enable(isolated_twofa)
        client = _client()
        client.cookies.set("sonar_2fa_pending", new_pending_token("user-1"))
        assert (
            client.post("/api/2fa/verify-login", json={"code": "000000"}).status_code
            == 400
        )

    def test_verify_login_no_pending_token(self, isolated_twofa):
        self._enable(isolated_twofa)
        assert (
            _client().post("/api/2fa/verify-login", json={"code": "123456"}).status_code
            == 401
        )

    def test_verify_login_code_direct(self, isolated_twofa):
        secret = self._enable(isolated_twofa)
        ok, method = verify_login_code("user-1", totp.totp_code(secret))
        assert (ok, method) == (True, "totp")
        ok, _ = verify_login_code("user-1", "000000")
        assert ok is False

    def test_lockout_after_failures(self, isolated_twofa):
        self._enable(isolated_twofa)
        for _ in range(5):
            verify_login_code("user-1", "000000")
        record = isolated_twofa.get("user-1")
        assert record is not None
        assert is_locked(record) is True
        ok, method = verify_login_code("user-1", "000000")
        assert (ok, method) == (False, "locked")
