"""Tests for staff quota bypass, the admin console API, and owner bootstrap.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import oauth as oauth_module
from app.billing.quotas import check_quota
from app.billing.usage import get_usage_store
from app.main import app
from app.oauth import OAuthUser, OAuthUserStore, new_session_token, set_oauth_user_store

_TEST_SESSION_SECRET = "test-session-secret-for-admin-tests"


@pytest.fixture
def user_store(tmp_path: Path) -> Generator[OAuthUserStore, None, None]:
    """Swap in an isolated JSON user store."""
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth_module.get_oauth_user_store()
    set_oauth_user_store(store)
    yield store
    set_oauth_user_store(previous)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _make_user(store: OAuthUserStore, *, email: str, name: str = "User") -> OAuthUser:
    return store.upsert(
        provider="github",
        provider_user_id=f"uid-{email}",
        name=name,
        email=email,
        avatar_url="",
    )


def _auth_headers(user: OAuthUser, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SESSION_SECRET)
    monkeypatch.setattr(oauth_module, "_secret_warning_emitted", True)
    token = new_session_token(user.id, _TEST_SESSION_SECRET)
    return {"Cookie": f"sonar_session={token}"}


def _use_up_scans(user_id: str) -> None:
    store = get_usage_store()
    for _ in range(5):
        store.increment(user_id, "scans")


class TestStaffQuotaBypass:
    def test_staff_skips_quota_when_exhausted(self, user_store: OAuthUserStore) -> None:
        user = _make_user(user_store, email="staff@example.com")
        assert user_store.set_staff(user.id, True) is not None
        _use_up_scans(user.id)
        check_quota(user.id, "scans")  # must not raise
        check_quota(user.id, "ask_sonar")  # must not raise

    def test_non_staff_still_blocked_when_exhausted(self, user_store: OAuthUserStore) -> None:
        user = _make_user(user_store, email="regular@example.com")
        _use_up_scans(user.id)
        with pytest.raises(HTTPException) as excinfo:
            check_quota(user.id, "scans")
        assert excinfo.value.status_code == 402

    def test_staff_usage_still_recorded(self, user_store: OAuthUserStore) -> None:
        user = _make_user(user_store, email="metered@example.com")
        user_store.set_staff(user.id, True)
        _use_up_scans(user.id)
        usage = get_usage_store().get_usage(user.id)
        assert usage["scans_used"] == 5


class TestAdminApiGating:
    def test_unauthenticated_is_401(self, client: TestClient, user_store: OAuthUserStore) -> None:
        res = client.get("/api/admin/users")
        assert res.status_code == 401

    def test_non_admin_is_403(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _make_user(user_store, email="pleb@example.com")
        res = client.get("/api/admin/users", headers=_auth_headers(user, monkeypatch))
        assert res.status_code == 403

    def test_admin_can_list_users(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin = _make_user(user_store, email="admin@example.com")
        user_store.set_admin(admin.id, True)
        _make_user(user_store, email="other@example.com")
        res = client.get("/api/admin/users", headers=_auth_headers(admin, monkeypatch))
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 2
        emails = {u["email"] for u in body["users"]}
        assert emails == {"admin@example.com", "other@example.com"}
        admin_view = next(u for u in body["users"] if u["email"] == "admin@example.com")
        assert admin_view["is_admin"] is True
        assert admin_view["usage"]["scans_used"] == 0


class TestAdminFlagChanges:
    def test_admin_can_grant_and_revoke_staff(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin = _make_user(user_store, email="admin@example.com")
        user_store.set_admin(admin.id, True)
        target = _make_user(user_store, email="target@example.com")
        headers = _auth_headers(admin, monkeypatch)

        res = client.post(
            f"/api/admin/users/{target.id}/staff", json={"is_staff": True}, headers=headers
        )
        assert res.status_code == 200
        assert res.json()["user"]["is_staff"] is True
        assert user_store.get(target.id).is_staff is True

        res = client.post(
            f"/api/admin/users/{target.id}/staff", json={"is_staff": False}, headers=headers
        )
        assert res.status_code == 200
        assert res.json()["user"]["is_staff"] is False

    def test_admin_can_grant_admin(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin = _make_user(user_store, email="admin@example.com")
        user_store.set_admin(admin.id, True)
        target = _make_user(user_store, email="target@example.com")
        headers = _auth_headers(admin, monkeypatch)

        res = client.post(
            f"/api/admin/users/{target.id}/admin", json={"is_admin": True}, headers=headers
        )
        assert res.status_code == 200
        assert res.json()["user"]["is_admin"] is True

    def test_admin_cannot_change_own_admin_flag(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin = _make_user(user_store, email="admin@example.com")
        user_store.set_admin(admin.id, True)
        headers = _auth_headers(admin, monkeypatch)

        res = client.post(
            f"/api/admin/users/{admin.id}/admin", json={"is_admin": False}, headers=headers
        )
        assert res.status_code == 400
        assert user_store.get(admin.id).is_admin is True

    def test_demote_other_admin_allowed_while_you_remain(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin = _make_user(user_store, email="admin@example.com")
        user_store.set_admin(admin.id, True)
        target = _make_user(user_store, email="target@example.com")
        user_store.set_admin(target.id, True)
        headers = _auth_headers(admin, monkeypatch)

        # Demoting another admin is fine while the caller remains admin.
        res = client.post(
            f"/api/admin/users/{target.id}/admin", json={"is_admin": False}, headers=headers
        )
        assert res.status_code == 200
        assert user_store.get(target.id).is_admin is False
        assert user_store.get(admin.id).is_admin is True

        # With a single admin left, nobody can remove them: self-demotion
        # is blocked, and there is no other admin to do it.
        res = client.post(
            f"/api/admin/users/{admin.id}/admin", json={"is_admin": False}, headers=headers
        )
        assert res.status_code == 400
        assert user_store.get(admin.id).is_admin is True

    def test_unknown_user_is_404(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin = _make_user(user_store, email="admin@example.com")
        user_store.set_admin(admin.id, True)
        headers = _auth_headers(admin, monkeypatch)
        res = client.post("/api/admin/users/nope/staff", json={"is_staff": True}, headers=headers)
        assert res.status_code == 404


class TestOwnerBootstrap:
    def _bootstrap(self, user: OAuthUser, monkeypatch: pytest.MonkeyPatch) -> OAuthUser:
        from app.oauth import _maybe_bootstrap_owner

        return _maybe_bootstrap_owner(user)

    def test_no_env_var_no_change(
        self, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CODESONAR_OWNER_EMAIL", raising=False)
        user = _make_user(user_store, email="owner@example.com")
        updated = self._bootstrap(user, monkeypatch)
        assert updated.is_admin is False
        assert updated.is_staff is False

    def test_matching_email_becomes_admin_and_staff(
        self, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODESONAR_OWNER_EMAIL", "Owner@Example.com")
        user = _make_user(user_store, email="owner@example.com")
        updated = self._bootstrap(user, monkeypatch)
        assert updated.is_admin is True
        assert updated.is_staff is True

    def test_non_matching_email_unchanged(
        self, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODESONAR_OWNER_EMAIL", "owner@example.com")
        user = _make_user(user_store, email="someone@example.com")
        updated = self._bootstrap(user, monkeypatch)
        assert updated.is_admin is False
        assert updated.is_staff is False

    def test_noop_when_admin_already_exists(
        self, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODESONAR_OWNER_EMAIL", "owner@example.com")
        existing = _make_user(user_store, email="existing-admin@example.com")
        user_store.set_admin(existing.id, True)
        user = _make_user(user_store, email="owner@example.com")
        updated = self._bootstrap(user, monkeypatch)
        assert updated.is_admin is False
        assert updated.is_staff is False

    def test_me_includes_flags(
        self, client: TestClient, user_store: OAuthUserStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _make_user(user_store, email="flags@example.com")
        user_store.set_admin(user.id, True)
        user_store.set_staff(user.id, True)
        res = client.get("/api/auth/me", headers=_auth_headers(user, monkeypatch))
        assert res.status_code == 200
        body: dict[str, Any] = res.json()
        assert body["is_admin"] is True
        assert body["is_staff"] is True
        assert body["plan"] == "free"
