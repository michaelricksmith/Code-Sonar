"""Tests for retention Phases 3 and 4: digest, streaks, churn, nudges.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.digest.preferences import (
    InMemoryEmailPreferenceStore,
    get_email_preference_store,
    set_email_preference_store,
    unsubscribe_token,
    verify_unsubscribe_token,
)
from app.digest.service import build_digest
from app.digest.templates import render_html, render_text
from app.fix_tracking.models import FixAttempt
from app.fix_tracking.runtime import get_fix_attempt_store, set_fix_attempt_store
from app.fix_tracking.service import user_fix_stats, user_fix_streak
from app.fix_tracking.store import InMemoryFixAttemptStore
from app.history import SCHEMA_VERSION
from app.history.history_store import InMemoryHistoryStore
from app.history.scan_record import ScanRecord
from app.main import app, get_history_store, set_history_store
from app.retention.churn import generate_nudge, user_churn_signals
from app.security.tenant import LOCAL_TENANT_ID


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _mk_record(
    scan_id: str,
    repo_id: str,
    scanned_at: str,
    owner: str | None = "user-1",
    score: int = 700,
    finding_count: int = 2,
    drift_summary: dict | None = None,
) -> ScanRecord:
    return ScanRecord.from_dict(
        {
            "scan_id": scan_id,
            "tenant_id": LOCAL_TENANT_ID,
            "owner_user_id": owner,
            "repository_id": repo_id,
            "repository_path": "/tmp/repo",
            "repository_slug": "octo/" + repo_id,
            "scanned_at": scanned_at,
            "schema_version": SCHEMA_VERSION,
            "score": score,
            "grade": "B",
            "total_debt_points": 10,
            "finding_count": finding_count,
            "category_scores": {},
            "severity_distribution": {},
            "findings_by_category": {},
            "findings_source_breakdown": {},
            "findings": [],
            "drift_summary": drift_summary,
        }
    )


def _mk_attempt(**overrides) -> FixAttempt:
    data = {
        "attempt_id": "a1",
        "user_id": "user-1",
        "repository_id": "repo-1",
        "finding_id": "f1",
        "rule_id": "r1",
        "file_path": "a.py",
        "copied_at": "2026-10-01T00:00:00+00:00",
    }
    data.update(overrides)
    return FixAttempt.from_dict(data)


@pytest.fixture()
def isolated_history():
    original = get_history_store()
    store = InMemoryHistoryStore()
    set_history_store(store)
    try:
        yield store
    finally:
        set_history_store(original)


@pytest.fixture()
def isolated_attempts():
    original = get_fix_attempt_store()
    store = InMemoryFixAttemptStore()
    set_fix_attempt_store(store)
    try:
        yield store
    finally:
        set_fix_attempt_store(original)


@pytest.fixture()
def isolated_prefs():
    original = get_email_preference_store()
    store = InMemoryEmailPreferenceStore()
    set_email_preference_store(store)
    try:
        yield store
    finally:
        set_email_preference_store(original)


@pytest.fixture(autouse=True)
def _signed_in_user(monkeypatch: pytest.MonkeyPatch):
    import app.oauth as oauth_module

    monkeypatch.setattr(
        oauth_module, "current_user", lambda r: SimpleNamespace(id="user-1")
    )


# ---------------------------------------------------------------------------
# Digest service
# ---------------------------------------------------------------------------


class TestBuildDigest:
    def test_empty_without_activity(self, isolated_history):
        digest = build_digest("user-1", isolated_history)
        assert digest["has_activity"] is False

    def test_digest_content(
        self, isolated_history, isolated_attempts: InMemoryFixAttemptStore
    ):
        now = datetime.now(timezone.utc)
        isolated_history.append(
            _mk_record(
                "s1",
                "repo-1",
                (now - timedelta(days=2)).isoformat(),
                drift_summary={"score_delta": 20, "new_count": 1, "resolved_count": 2},
            )
        )
        isolated_history.append(
            _mk_record("s2", "repo-2", (now - timedelta(days=1)).isoformat())
        )
        isolated_attempts.append(_mk_attempt(attempt_id="a1"))
        isolated_attempts.mark_verified(
            "a1",
            verified_at=now.isoformat(),
            verified_scan_id="s1",
            score_delta=20,
        )
        digest = build_digest("user-1", isolated_history)
        assert digest["has_activity"] is True
        assert digest["total_repos"] == 2
        assert digest["verified_this_week"] == 1
        assert digest["cta"] is not None
        assert digest["cta"]["repository_label"] == "octo/repo-1"
        by_id = {r["repository_id"]: r for r in digest["repos"]}
        assert by_id["repo-1"]["score_delta"] == 20
        assert by_id["repo-1"]["resolved_count"] == 2

    def test_no_cta_when_no_open_issues(self, isolated_history):
        isolated_history.append(
            _mk_record(
                "s1", "repo-1", datetime.now(timezone.utc).isoformat(), finding_count=0
            )
        )
        digest = build_digest("user-1", isolated_history)
        assert digest["cta"] is None


class TestTemplates:
    def _digest(self):
        return {
            "user_id": "user-1",
            "has_activity": True,
            "repos": [
                {
                    "repository_id": "repo-1",
                    "repository_label": "octo/repo-1",
                    "score": 720,
                    "grade": "B",
                    "finding_count": 3,
                    "score_delta": 20,
                    "resolved_count": 2,
                }
            ],
            "verified_this_week": 2,
            "cta": {"repository_label": "octo/repo-1", "text": "Fix your 3 issues."},
        }

    def test_text_template(self):
        text = render_text(self._digest(), "https://x/unsub")
        assert "octo/repo-1" in text
        assert "720" in text
        assert "https://x/unsub" in text

    def test_html_template(self):
        html = render_html(self._digest(), "https://x/unsub")
        assert "<table" in html
        assert "octo/repo-1" in html
        assert "https://x/unsub" in html


# ---------------------------------------------------------------------------
# Preferences + unsubscribe tokens
# ---------------------------------------------------------------------------


class TestPreferences:
    def test_default_opted_in(self, isolated_prefs: InMemoryEmailPreferenceStore):
        assert isolated_prefs.is_digest_enabled("user-1") is True

    def test_unsubscribe_and_resubscribe(
        self, isolated_prefs: InMemoryEmailPreferenceStore
    ):
        isolated_prefs.set_digest_enabled("user-1", False)
        assert isolated_prefs.is_digest_enabled("user-1") is False
        isolated_prefs.set_digest_enabled("user-1", True)
        assert isolated_prefs.is_digest_enabled("user-1") is True

    def test_token_round_trip(self):
        token = unsubscribe_token("user-1")
        assert verify_unsubscribe_token(token) == "user-1"

    def test_token_tamper_rejected(self):
        token = unsubscribe_token("user-1")
        assert verify_unsubscribe_token(token + "x") is None
        assert verify_unsubscribe_token("garbage") is None
        assert verify_unsubscribe_token("") is None


class TestResendClient:
    def test_not_configured_by_default(self, monkeypatch: pytest.MonkeyPatch):
        from app.digest import resend_client

        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("DIGEST_FROM_ADDRESS", raising=False)
        assert resend_client.is_configured() is False
        with pytest.raises(resend_client.EmailNotConfiguredError):
            resend_client.send_email(
                to="a@b.c", subject="s", html="<p>x</p>", text="x"
            )


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------


class TestStreaks:
    def _verify_in_week(
        self, store: InMemoryFixAttemptStore, attempt_id: str, weeks_ago: int
    ):
        monday = datetime.now(timezone.utc) - timedelta(
            days=datetime.now(timezone.utc).weekday() + 7 * weeks_ago
        )
        verified_at = monday.replace(
            hour=12, minute=0, second=0, microsecond=0
        ).isoformat()
        store.append(_mk_attempt(attempt_id=attempt_id, copied_at=verified_at))
        assert store.mark_verified(
            attempt_id,
            verified_at=verified_at,
            verified_scan_id="s",
            score_delta=5,
        )

    def test_no_streak_without_fixes(self, isolated_attempts):
        assert user_fix_streak("user-1") == {
            "current_streak_weeks": 0,
            "longest_streak_weeks": 0,
        }

    def test_current_and_longest_streak(self, isolated_attempts):
        for i in range(3):
            self._verify_in_week(isolated_attempts, f"a{i}", weeks_ago=i)
        streak = user_fix_streak("user-1")
        assert streak["current_streak_weeks"] == 3
        assert streak["longest_streak_weeks"] == 3

    def test_broken_streak(self, isolated_attempts):
        self._verify_in_week(isolated_attempts, "a0", weeks_ago=0)
        self._verify_in_week(isolated_attempts, "a2", weeks_ago=2)
        self._verify_in_week(isolated_attempts, "a3", weeks_ago=3)
        streak = user_fix_streak("user-1")
        assert streak["current_streak_weeks"] == 1
        assert streak["longest_streak_weeks"] == 2

    def test_streak_in_stats(self, isolated_attempts):
        self._verify_in_week(isolated_attempts, "a0", weeks_ago=0)
        stats = user_fix_stats("user-1")
        assert stats["streak"]["current_streak_weeks"] == 1


# ---------------------------------------------------------------------------
# Churn signals + nudges
# ---------------------------------------------------------------------------


class TestChurn:
    def test_no_signals_without_records(self, isolated_history, isolated_attempts):
        assert user_churn_signals("user-1", isolated_history) == []
        assert generate_nudge("user-1", isolated_history) is None

    def test_scanned_once_no_fix(self, isolated_history, isolated_attempts):
        isolated_history.append(
            _mk_record("s1", "repo-1", datetime.now(timezone.utc).isoformat())
        )
        signals = user_churn_signals("user-1", isolated_history)
        assert [s["signal"] for s in signals] == ["scanned_once_no_fix"]
        nudge = generate_nudge("user-1", isolated_history)
        assert nudge["signal"] == "scanned_once_no_fix"
        assert "octo/repo-1" in nudge["text"]
        assert "we miss you" not in nudge["text"].lower()

    def test_fix_no_rescan(self, isolated_history, isolated_attempts):
        now = datetime.now(timezone.utc)
        isolated_history.append(
            _mk_record("s1", "repo-1", (now - timedelta(days=20)).isoformat())
        )
        isolated_attempts.append(
            _mk_attempt(copied_at=(now - timedelta(days=5)).isoformat())
        )
        signals = user_churn_signals("user-1", isolated_history)
        assert "fix_no_rescan" in [s["signal"] for s in signals]
        nudge = generate_nudge("user-1", isolated_history)
        assert nudge["signal"] == "fix_no_rescan"
        assert "a.py" in nudge["text"]

    def test_dormant(self, isolated_history, isolated_attempts):
        now = datetime.now(timezone.utc)
        for i in range(3):
            isolated_history.append(
                _mk_record(
                    f"s{i}",
                    "repo-1",
                    (now - timedelta(days=30 - i)).isoformat(),
                )
            )
        signals = user_churn_signals("user-1", isolated_history)
        assert signals[0]["signal"] == "dormant"
        assert signals[0]["days_since_scan"] >= 14
        nudge = generate_nudge("user-1", isolated_history)
        assert "rescan automatically" in nudge["text"]

    def test_active_user_gets_no_nudge(self, isolated_history, isolated_attempts):
        now = datetime.now(timezone.utc)
        isolated_history.append(
            _mk_record("s1", "repo-1", now.isoformat())
        )
        isolated_attempts.append(
            _mk_attempt(copied_at=(now - timedelta(minutes=5)).isoformat())
        )
        assert generate_nudge("user-1", isolated_history) is None


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestDigestApi:
    def test_preview_requires_sign_in(
        self, isolated_history, monkeypatch: pytest.MonkeyPatch
    ):
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        assert _client().get("/api/digest/preview").status_code == 401

    def test_preview_empty(self, isolated_history):
        body = _client().get("/api/digest/preview").json()
        assert body["has_activity"] is False

    def test_preview_with_activity(self, isolated_history):
        isolated_history.append(
            _mk_record("s1", "repo-1", datetime.now(timezone.utc).isoformat())
        )
        body = _client().get("/api/digest/preview").json()
        assert body["has_activity"] is True
        assert "email_text" in body
        assert "email_html" in body
        assert "octo/repo-1" in body["email_text"]

    def test_status(self, isolated_history, isolated_prefs):
        body = _client().get("/api/digest/status").json()
        assert body["digest_enabled"] is True
        assert "sending_configured" in body

    def test_preferences_opt_out(self, isolated_history, isolated_prefs):
        resp = _client().post("/api/digest/preferences", json={"digest_enabled": False})
        assert resp.json() == {"ok": True, "digest_enabled": False}
        assert _client().get("/api/digest/status").json()["digest_enabled"] is False

    def test_unsubscribe_token(self, isolated_history, isolated_prefs):
        token = unsubscribe_token("user-1")
        resp = _client().get("/api/digest/unsubscribe", params={"token": token})
        assert resp.json()["ok"] is True
        assert isolated_prefs.is_digest_enabled("user-1") is False

    def test_unsubscribe_bad_token(self, isolated_history, isolated_prefs):
        assert (
            _client()
            .get("/api/digest/unsubscribe", params={"token": "bogus"})
            .status_code
            == 400
        )


class TestRetentionApi:
    def test_nudge_requires_sign_in(
        self, isolated_history, monkeypatch: pytest.MonkeyPatch
    ):
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        assert _client().get("/api/retention/nudge").status_code == 401

    def test_nudge_none_when_active(self, isolated_history, isolated_attempts):
        now = datetime.now(timezone.utc)
        isolated_history.append(_mk_record("s1", "repo-1", now.isoformat()))
        isolated_attempts.append(
            _mk_attempt(copied_at=(now - timedelta(minutes=5)).isoformat())
        )
        body = _client().get("/api/retention/nudge").json()
        assert body["nudge"] is None
        assert body["signals"] == []

    def test_nudge_for_dormant(self, isolated_history, isolated_attempts):
        now = datetime.now(timezone.utc)
        for i in range(3):
            isolated_history.append(
                _mk_record(f"s{i}", "repo-1", (now - timedelta(days=30 - i)).isoformat())
            )
        body = _client().get("/api/retention/nudge").json()
        assert body["nudge"]["signal"] == "dormant"
        assert "octo/repo-1" in body["nudge"]["text"]
