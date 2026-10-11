"""Tests for server-side sessions and security event logging.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security_events.events import (
    LOGIN_SUCCESS,
    NEW_DEVICE_LOGIN,
    InMemorySecurityEventStore,
    get_security_event_store,
    log_event,
    log_login_success,
    set_security_event_store,
)
from app.sessions.sessions import (
    InMemorySessionStore,
    decode_access_token,
    get_session_store,
    hash_refresh_token,
    new_access_token,
    set_session_store,
)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def isolated_sessions():
    original = get_session_store()
    store = InMemorySessionStore()
    set_session_store(store)
    try:
        yield store
    finally:
        set_session_store(original)


@pytest.fixture()
def isolated_events():
    original = get_security_event_store()
    store = InMemorySecurityEventStore()
    set_security_event_store(store)
    try:
        yield store
    finally:
        set_security_event_store(original)


@pytest.fixture(autouse=True)
def _signed_in_user(monkeypatch: pytest.MonkeyPatch):
    import app.oauth as oauth_module

    monkeypatch.setattr(
        oauth_module, "current_user", lambda r: SimpleNamespace(id="user-1")
    )
    monkeypatch.setattr(
        oauth_module,
        "current_session_id",
        lambda r: getattr(r, "_test_session_id", None),
    )


class TestSessions:
    def test_create_and_get(self, isolated_sessions: InMemorySessionStore):
        session = isolated_sessions.create(
            "user-1", hash_refresh_token("rt"), device_info="d", ip_address="1.2.3.4"
        )
        assert isolated_sessions.get(session.session_id) is not None
        assert isolated_sessions.get(session.session_id).user_id == "user-1"

    def test_revoke(self, isolated_sessions: InMemorySessionStore):
        session = isolated_sessions.create(
            "user-1", hash_refresh_token("rt"), device_info=None, ip_address=None
        )
        assert isolated_sessions.revoke(session.session_id) is True
        assert isolated_sessions.get(session.session_id).revoked is True
        assert isolated_sessions.revoke(session.session_id) is False

    def test_revoke_all_except_current(
        self, isolated_sessions: InMemorySessionStore
    ):
        s1 = isolated_sessions.create(
            "user-1", hash_refresh_token("a"), device_info=None, ip_address=None
        )
        s2 = isolated_sessions.create(
            "user-1", hash_refresh_token("b"), device_info=None, ip_address=None
        )
        count = isolated_sessions.revoke_all_for_user("user-1", s1.session_id)
        assert count == 1
        assert isolated_sessions.get(s1.session_id).revoked is False
        assert isolated_sessions.get(s2.session_id).revoked is True

    def test_rotate_refresh(self, isolated_sessions: InMemorySessionStore):
        session = isolated_sessions.create(
            "user-1", hash_refresh_token("old"), device_info=None, ip_address=None
        )
        assert isolated_sessions.rotate_refresh(
            session.session_id, hash_refresh_token("new")
        )
        assert (
            isolated_sessions.get_refresh_hash(session.session_id)
            == hash_refresh_token("new")
        )

    def test_access_token_round_trip(self):
        from app.oauth import _session_secret

        token = new_access_token("sess_123", "user-1", _session_secret())
        payload = decode_access_token(token, _session_secret())
        assert payload is not None
        assert payload["sid"] == "sess_123"
        assert payload["sub"] == "user-1"
        assert decode_access_token("garbage", _session_secret()) is None


class TestSessionApi:
    def _with_session(self, client: TestClient, session_id: str):
        # Simulate a request carrying the session via the test hook.
        class Req:
            _test_session_id = session_id

        return Req()

    def test_list_sessions_empty(self, isolated_sessions):
        body = _client().get("/api/sessions").json()
        assert body["sessions"] == []

    def test_list_sessions(
        self, isolated_sessions: InMemorySessionStore, monkeypatch
    ):
        import app.oauth as oauth_module

        s1 = isolated_sessions.create(
            "user-1",
            hash_refresh_token("a"),
            device_info="Chrome",
            ip_address="1.2.3.4",
        )
        monkeypatch.setattr(
            oauth_module, "current_session_id", lambda r: s1.session_id
        )
        body = _client().get("/api/sessions").json()
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["session_id"] == s1.session_id
        assert body["sessions"][0]["is_current"] is True
        assert body["sessions"][0]["device_info"] == "Chrome"

    def test_revoke_session(
        self, isolated_sessions: InMemorySessionStore, monkeypatch
    ):
        import app.oauth as oauth_module

        s1 = isolated_sessions.create(
            "user-1", hash_refresh_token("a"), device_info=None, ip_address=None
        )
        s2 = isolated_sessions.create(
            "user-1", hash_refresh_token("b"), device_info=None, ip_address=None
        )
        monkeypatch.setattr(
            oauth_module, "current_session_id", lambda r: s1.session_id
        )
        resp = _client().post(f"/api/sessions/{s2.session_id}/revoke")
        assert resp.json() == {"ok": True}
        assert isolated_sessions.get(s2.session_id).revoked is True

    def test_cannot_revoke_current(
        self, isolated_sessions: InMemorySessionStore, monkeypatch
    ):
        import app.oauth as oauth_module

        s1 = isolated_sessions.create(
            "user-1", hash_refresh_token("a"), device_info=None, ip_address=None
        )
        monkeypatch.setattr(
            oauth_module, "current_session_id", lambda r: s1.session_id
        )
        resp = _client().post(f"/api/sessions/{s1.session_id}/revoke")
        assert resp.status_code == 400

    def test_revoke_other_users_session_forbidden(
        self, isolated_sessions: InMemorySessionStore, monkeypatch
    ):
        import app.oauth as oauth_module

        s1 = isolated_sessions.create(
            "user-1", hash_refresh_token("a"), device_info=None, ip_address=None
        )
        other = isolated_sessions.create(
            "user-2", hash_refresh_token("b"), device_info=None, ip_address=None
        )
        monkeypatch.setattr(
            oauth_module, "current_session_id", lambda r: s1.session_id
        )
        resp = _client().post(f"/api/sessions/{other.session_id}/revoke")
        assert resp.status_code == 404

    def test_revoke_others(
        self, isolated_sessions: InMemorySessionStore, monkeypatch
    ):
        import app.oauth as oauth_module

        s1 = isolated_sessions.create(
            "user-1", hash_refresh_token("a"), device_info=None, ip_address=None
        )
        isolated_sessions.create(
            "user-1", hash_refresh_token("b"), device_info=None, ip_address=None
        )
        monkeypatch.setattr(
            oauth_module, "current_session_id", lambda r: s1.session_id
        )
        body = _client().post("/api/sessions/revoke-others").json()
        assert body["revoked"] == 1

    def test_refresh_rotates(
        self, isolated_sessions: InMemorySessionStore, monkeypatch
    ):
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "_session_secret", lambda: "test-secret")
        session = isolated_sessions.create(
            "user-1", hash_refresh_token("rt1"), device_info=None, ip_address=None
        )
        client = _client()
        client.cookies.set(
            "sonar_refresh", f"{session.session_id}.rt1", path="/api/auth/refresh"
        )
        resp = client.post("/api/auth/refresh")
        assert resp.status_code == 200
        # Old refresh token is dead after rotation.
        client2 = _client()
        client2.cookies.set(
            "sonar_refresh", f"{session.session_id}.rt1", path="/api/auth/refresh"
        )
        assert client2.post("/api/auth/refresh").status_code == 401


class TestSecurityEvents:
    def test_log_login_marks_new_device(
        self, isolated_events: InMemorySecurityEventStore
    ):
        is_new = log_login_success(
            "user-1", ip_address="1.2.3.4", user_agent="UA", provider="github"
        )
        assert is_new is True
        types = [e.event_type for e in isolated_events.list_for_user("user-1")]
        assert LOGIN_SUCCESS in types
        assert NEW_DEVICE_LOGIN in types

    def test_second_login_same_device_not_new(
        self, isolated_events: InMemorySecurityEventStore
    ):
        log_login_success(
            "user-1", ip_address="1.2.3.4", user_agent="UA", provider="github"
        )
        is_new = log_login_success(
            "user-1", ip_address="1.2.3.4", user_agent="UA", provider="github"
        )
        assert is_new is False

    def test_log_event_never_raises(self, isolated_events, monkeypatch):
        import app.security_events.events as events_module

        monkeypatch.setattr(
            events_module, "get_security_event_store", lambda: (_ for _ in ()).throw(
                RuntimeError("boom")
            )
        )
        event = log_event("login_success", user_id="user-1")
        assert event.event_id == "se_dropped"

    def test_events_api_requires_sign_in(self, isolated_events, monkeypatch):
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        assert _client().get("/api/security/events").status_code == 401

    def test_events_api(self, isolated_events):
        log_login_success(
            "user-1", ip_address="1.2.3.4", user_agent="UA", provider="github"
        )
        body = _client().get("/api/security/events").json()
        assert len(body["events"]) == 2
        assert body["events"][0]["event_type"] in (LOGIN_SUCCESS, NEW_DEVICE_LOGIN)
