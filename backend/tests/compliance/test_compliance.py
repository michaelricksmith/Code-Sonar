"""Tests for pre-public-launch consumer compliance.

No network access: Stripe SDK calls are faked, emails go through the log
transport into a temp outbox dir, and persistence is the JSON fallback in a
temp dir.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi.testclient import TestClient

from app import oauth as oauth_module
from app.compliance import email as email_module
from app.compliance import reminders as reminders_module
from app.compliance.records import (
    AGE_GATE,
    ANNUAL_REMINDER_SENT,
    AUTORENEW_CONSENT,
    CANCELLATION,
    GPC_OPTOUT,
    MARKETING_CONSENT,
    JsonComplianceRecordStore,
    get_compliance_store,
    set_compliance_store,
)
from app.main import app
from app.oauth import OAuthUser, OAuthUserStore, new_session_token, set_oauth_user_store

_TEST_SESSION_SECRET = "test-session-secret-compliance"
_TEST_WEBHOOK_SECRET = "whsec_test_compliance"
_HOBBY_PRICE = "price_test_hobby"
_PLUS_PRICE = "price_test_plus"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def billing_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_billing")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", _TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_PRICE_HOBBY", _HOBBY_PRICE)
    monkeypatch.setenv("STRIPE_PRICE_PLUS", _PLUS_PRICE)
    monkeypatch.setenv("SONAR_EMAIL_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("SONAR_EMAIL_TRANSPORT", "log")


@pytest.fixture
def user_store(tmp_path: Path) -> Generator[tuple[OAuthUserStore, OAuthUser], None, None]:
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth_module.get_oauth_user_store()
    set_oauth_user_store(store)
    user = store.upsert(
        provider="github",
        provider_user_id="4242",
        name="Compliance User",
        email="compliance@example.com",
        avatar_url="",
    )
    yield store, user
    set_oauth_user_store(previous)


@pytest.fixture
def compliance_store(
    tmp_path: Path,
) -> Generator[JsonComplianceRecordStore, None, None]:
    store = JsonComplianceRecordStore(path=tmp_path / "compliance.json")
    previous = get_compliance_store()
    set_compliance_store(store)
    yield store
    set_compliance_store(previous)


@pytest.fixture
def auth_headers(
    user_store: tuple[OAuthUserStore, OAuthUser],
    compliance_store: JsonComplianceRecordStore,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, str], OAuthUser]:
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SESSION_SECRET)
    monkeypatch.setattr(oauth_module, "_secret_warning_emitted", True)
    _, user = user_store
    token = new_session_token(user.id, _TEST_SESSION_SECRET)
    return {"Cookie": f"sonar_session={token}"}, user


def _outbox(tmp_path: Path) -> list[dict[str, Any]]:
    outbox = tmp_path / "outbox"
    if not outbox.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(outbox.glob("*.json"))]


# -- age gate ---------------------------------------------------------------


def test_age_gate_adult_records_bracket_not_birth_year(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    current_year = dt.date.today().year
    resp = client.post(
        "/api/compliance/age-gate",
        json={"birth_year": current_year - 30},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["bracket"] == "18+"
    record = compliance_store.latest(user.id, AGE_GATE)
    assert record is not None
    assert record.payload["bracket"] == "18+"
    assert "birth_year" not in json.dumps(record.payload)


def test_age_gate_teen_bracket(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    current_year = dt.date.today().year
    resp = client.post(
        "/api/compliance/age-gate",
        json={"birth_year": current_year - 15},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["bracket"] == "13-17"


def test_age_gate_under_13_blocked_and_scrubbed(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    store, _ = user_store
    current_year = dt.date.today().year
    resp = client.post(
        "/api/compliance/age-gate",
        json={"birth_year": current_year - 10},
        headers=headers,
    )
    assert resp.status_code == 403
    # No age-gate record is retained for the blocked attempt.
    assert compliance_store.latest(user.id, AGE_GATE) is None
    resp = client.post("/api/compliance/age-gate/block", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["scrubbed"] is True
    scrubbed = store.get(user.id)
    assert scrubbed is None  # the record is deleted, not retained


def test_compliance_status_reflects_age_gate(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
) -> None:
    headers, _ = auth_headers
    status = client.get("/api/compliance/status", headers=headers).json()
    assert status["age_gate_completed"] is False
    current_year = dt.date.today().year
    client.post(
        "/api/compliance/age-gate",
        json={"birth_year": current_year - 40},
        headers=headers,
    )
    status = client.get("/api/compliance/status", headers=headers).json()
    assert status["age_gate_completed"] is True
    assert status["age_bracket"] == "18+"


# -- marketing consent + one-click unsubscribe --------------------------------


def test_marketing_consent_opt_in_and_out(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    resp = client.post(
        "/api/compliance/marketing-consent", json={"opt_in": True}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["opt_in"] is True
    latest = compliance_store.latest(user.id, MARKETING_CONSENT)
    assert latest is not None and latest.payload["opt_in"] is True
    client.post(
        "/api/compliance/marketing-consent", json={"opt_in": False}, headers=headers
    )
    latest = compliance_store.latest(user.id, MARKETING_CONSENT)
    assert latest is not None and latest.payload["opt_in"] is False


def test_one_click_unsubscribe_needs_no_auth(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    _, user = auth_headers
    client.post("/api/compliance/marketing-consent", json={"opt_in": True})
    token = email_module.unsubscribe_token(user.id)
    resp = client.post(f"/api/compliance/unsubscribe/{token}")
    assert resp.status_code == 200
    latest = compliance_store.latest(user.id, MARKETING_CONSENT)
    assert latest is not None
    assert latest.payload["opt_in"] is False
    assert latest.payload["via"] == "one-click-unsubscribe"


def test_one_click_unsubscribe_bad_token_rejected(client: TestClient) -> None:
    resp = client.post("/api/compliance/unsubscribe/not-a-token")
    assert resp.status_code == 400


# -- GPC ----------------------------------------------------------------------


def test_gpc_opt_out_recorded(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    resp = client.post("/api/compliance/gpc", json={"gpc": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["honored"] is True
    record = compliance_store.latest(user.id, GPC_OPTOUT)
    assert record is not None
    assert record.payload["gpc"] is True
    assert record.payload["honored"] is True


# -- checkout consent ----------------------------------------------------------


def test_checkout_requires_autorenew_consent(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    resp = client.post(
        "/api/billing/checkout", json={"tier": "hobby"}, headers=headers
    )
    assert resp.status_code == 400
    assert "consent" in resp.json()["detail"].lower()
    assert compliance_store.latest(user.id, AUTORENEW_CONSENT) is None


def test_checkout_with_consent_records_and_proceeds(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    headers, user = auth_headers
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.test/session"
    with patch("stripe.checkout.Session.create", return_value=fake_session):
        resp = client.post(
            "/api/billing/checkout",
            json={"tier": "hobby", "autorenew_consent": True},
            headers=headers,
        )
    assert resp.status_code == 200
    assert resp.json()["checkout_url"] == "https://checkout.stripe.test/session"
    record = compliance_store.latest(user.id, AUTORENEW_CONSENT)
    assert record is not None
    assert record.payload["tier"] == "hobby"
    assert record.payload["amount"] == "$7"
    assert record.payload["frequency"] == "monthly"
    assert record.payload["terms_version"]


# -- cancel / resume ------------------------------------------------------------


def _stripe_session(fake_sub: Any) -> None:
    fake_sub.id = "sub_test_123"
    fake_sub.status = "active"
    fake_sub.cancel_at_period_end = False
    fake_sub.current_period_end = int(time.time()) + 2_592_000
    fake_sub.canceled_at = None


def _patch_stripe_subscription(
    monkeypatch: pytest.MonkeyPatch, fake_sub: Any
) -> None:
    fake_api = MagicMock()
    fake_api.Subscription.retrieve.return_value = fake_sub
    fake_api.Subscription.modify.side_effect = lambda sid, **kw: setattr(
        fake_sub, "cancel_at_period_end", kw.get("cancel_at_period_end", False)
    ) or fake_sub
    fake_api.Subscription.list.return_value = MagicMock(
        auto_paging_iter=lambda: iter([fake_sub])
    )
    monkeypatch.setattr(stripe, "Subscription", fake_api.Subscription)


def test_cancel_requires_paid_plan(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
) -> None:
    headers, _ = auth_headers
    resp = client.post("/api/billing/cancel", headers=headers)
    assert resp.status_code == 400


def test_cancel_schedules_at_period_end_and_emails(
    client: TestClient,
    billing_env: None,
    tmp_path: Path,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    compliance_store: JsonComplianceRecordStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user = user_store
    store.set_billing(user.id, plan="hobby", stripe_customer_id="cus_test_1")
    fake_sub = MagicMock()
    _stripe_session(fake_sub)
    _patch_stripe_subscription(monkeypatch, fake_sub)

    headers, _ = auth_headers
    resp = client.post("/api/billing/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["effective_at"]
    assert fake_sub.cancel_at_period_end is True

    record = compliance_store.latest(user.id, CANCELLATION)
    assert record is not None
    assert record.payload["source"] == "in-app"
    assert record.payload["scheduled"] is True
    assert record.payload["stripe_subscription_id"] == "sub_test_123"

    sent = _outbox(tmp_path)
    assert any(
        "cancel" in entry["subject"].lower() and entry["kind"] == "transactional"
        for entry in sent
    )


def test_resume_clears_scheduled_cancel(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    compliance_store: JsonComplianceRecordStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user = user_store
    store.set_billing(user.id, plan="hobby", stripe_customer_id="cus_test_1")
    fake_sub = MagicMock()
    _stripe_session(fake_sub)
    fake_sub.cancel_at_period_end = True
    _patch_stripe_subscription(monkeypatch, fake_sub)
    compliance_store.append(
        user_id=user.id,
        record_type=CANCELLATION,
        payload={"source": "in-app", "scheduled": True},
    )

    headers, _ = auth_headers
    resp = client.post("/api/billing/resume", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["cancel_at_period_end"] is False
    assert fake_sub.cancel_at_period_end is False
    record = compliance_store.latest(user.id, CANCELLATION)
    assert record is not None and record.payload.get("resumed") is True


def test_resume_without_scheduled_cancel_rejected(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user = user_store
    store.set_billing(user.id, plan="hobby", stripe_customer_id="cus_test_1")
    fake_sub = MagicMock()
    _stripe_session(fake_sub)
    _patch_stripe_subscription(monkeypatch, fake_sub)

    headers, _ = auth_headers
    resp = client.post("/api/billing/resume", headers=headers)
    assert resp.status_code == 400


def test_subscription_state_endpoint(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, user = user_store
    headers, _ = auth_headers
    resp = client.get("/api/billing/subscription", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"
    assert resp.json()["subscription"] is None

    store.set_billing(user.id, plan="plus", stripe_customer_id="cus_test_1")
    fake_sub = MagicMock()
    _stripe_session(fake_sub)
    _patch_stripe_subscription(monkeypatch, fake_sub)
    resp = client.get("/api/billing/subscription", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "plus"
    assert body["subscription"]["status"] == "active"
    assert body["subscription"]["cancel_at_period_end"] is False


# -- webhooks: receipts + cancellation records -----------------------------------


def _signed_webhook(event: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(event, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(
        f"{timestamp}.{raw.decode('utf-8')}", _TEST_WEBHOOK_SECRET
    )
    return raw, {"stripe-signature": f"t={timestamp},v1={signature}"}


def _event(event_type: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "evt_test_compliance",
        "object": "event",
        "type": event_type,
        "data": {"object": obj},
    }


def test_checkout_webhook_sends_receipt_and_records_subscription(
    client: TestClient,
    billing_env: None,
    tmp_path: Path,
    auth_headers: tuple[dict[str, str], OAuthUser],
    compliance_store: JsonComplianceRecordStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, user = auth_headers
    fake_sub = MagicMock()
    _stripe_session(fake_sub)
    monkeypatch.setattr(
        stripe, "Subscription", MagicMock(retrieve=MagicMock(return_value=fake_sub))
    )

    session = {
        "id": "cs_test_1",
        "object": "checkout.session",
        "client_reference_id": user.id,
        "customer": "cus_test_1",
        "subscription": "sub_test_123",
        "metadata": {"user_id": user.id, "tier": "hobby"},
        "line_items": {"data": [{"price": {"id": _HOBBY_PRICE}}]},
    }
    raw, headers = _signed_webhook(_event("checkout.session.completed", session))
    resp = client.post(
        "/api/billing/webhook", content=raw, headers={**headers, "Content-Type": "application/json"}
    )
    assert resp.status_code == 200

    records = compliance_store.history(user.id, AUTORENEW_CONSENT)
    assert records
    assert records[-1].payload["stripe_subscription_id"] == "sub_test_123"

    sent = _outbox(tmp_path)
    receipts = [e for e in sent if "subscription is active" in e["subject"]]
    assert receipts
    assert "$7/month" in receipts[-1]["text_body"] or "$7" in receipts[-1]["text_body"]
    assert receipts[-1]["kind"] == "transactional"


def test_subscription_deleted_webhook_records_and_emails(
    client: TestClient,
    billing_env: None,
    tmp_path: Path,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    store, user = user_store
    store.set_billing(user.id, plan="hobby", stripe_customer_id="cus_test_1")

    subscription = {
        "id": "sub_test_123",
        "object": "subscription",
        "status": "canceled",
        "metadata": {"user_id": user.id},
    }
    raw, headers = _signed_webhook(
        _event("customer.subscription.deleted", subscription)
    )
    resp = client.post(
        "/api/billing/webhook", content=raw, headers={**headers, "Content-Type": "application/json"}
    )
    assert resp.status_code == 200
    assert store.get(user.id).plan == "free"

    record = compliance_store.latest(user.id, CANCELLATION)
    assert record is not None
    assert record.payload["source"] == "webhook"
    assert record.payload["completed"] is True

    sent = _outbox(tmp_path)
    assert any("cancelled" in e["subject"].lower() for e in sent)


def test_subscription_updated_portal_cancel_tracked(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
    user_store: tuple[OAuthUserStore, OAuthUser],
    compliance_store: JsonComplianceRecordStore,
) -> None:
    store, user = user_store
    store.set_billing(user.id, plan="hobby", stripe_customer_id="cus_test_1")

    subscription = {
        "id": "sub_test_123",
        "object": "subscription",
        "status": "active",
        "cancel_at_period_end": True,
        "metadata": {"user_id": user.id},
        "items": {"data": [{"price": {"id": _HOBBY_PRICE}}]},
    }
    raw, headers = _signed_webhook(
        _event("customer.subscription.updated", subscription)
    )
    resp = client.post(
        "/api/billing/webhook", content=raw, headers={**headers, "Content-Type": "application/json"}
    )
    assert resp.status_code == 200
    record = compliance_store.latest(user.id, CANCELLATION)
    assert record is not None
    assert record.payload["source"] == "stripe-portal"
    assert record.payload["scheduled"] is True


# -- records: append-only ---------------------------------------------------------


def test_records_append_only_and_ordered(
    compliance_store: JsonComplianceRecordStore,
) -> None:
    a = compliance_store.append(user_id="u1", record_type=CANCELLATION, payload={"n": 1})
    b = compliance_store.append(user_id="u1", record_type=CANCELLATION, payload={"n": 2})
    history = compliance_store.history("u1", CANCELLATION)
    assert [r.record_id for r in history] == [a.record_id, b.record_id]
    assert compliance_store.latest("u1", CANCELLATION).record_id == b.record_id
    # No mutation API exists.
    assert not hasattr(compliance_store, "update")
    assert not hasattr(compliance_store, "delete")


# -- annual reminders -------------------------------------------------------------


def _fake_user(user_id: str, plan: str, email: str = "u@example.com"):
    class _U:
        pass

    u = _U()
    u.id = user_id
    u.plan = plan
    u.email = email
    return u


def test_annual_reminder_due_for_paid_without_record(
    compliance_store: JsonComplianceRecordStore,
) -> None:
    users = [_fake_user("u1", "hobby"), _fake_user("u2", "free")]
    due = reminders_module.due_annual_reminders(users, store=compliance_store)
    assert [d["user_id"] for d in due] == ["u1"]
    assert due[0]["amount"] == "$7"


def test_annual_reminder_not_due_after_recent_send(
    compliance_store: JsonComplianceRecordStore,
) -> None:
    compliance_store.append(
        user_id="u1", record_type=ANNUAL_REMINDER_SENT, payload={"plan": "hobby"}
    )
    due = reminders_module.due_annual_reminders(
        [_fake_user("u1", "hobby")], store=compliance_store
    )
    assert due == []


def test_annual_reminder_send_appends_record(
    tmp_path: Path, compliance_store: JsonComplianceRecordStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONAR_EMAIL_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("SONAR_EMAIL_TRANSPORT", "log")
    receipt = reminders_module.send_annual_reminder(
        {
            "user_id": "u1",
            "email": "u@example.com",
            "plan": "plus",
            "amount": "$14",
            "last_reminder_at": None,
        }
    )
    assert receipt["transport"] == "log"
    record = compliance_store.latest("u1", ANNUAL_REMINDER_SENT)
    assert record is not None
    assert record.payload["plan"] == "plus"


def test_annual_reminders_admin_gate(
    client: TestClient,
    billing_env: None,
    auth_headers: tuple[dict[str, str], OAuthUser],
) -> None:
    headers, _ = auth_headers
    resp = client.get("/api/compliance/reminders/annual", headers=headers)
    assert resp.status_code == 403


# -- email helpers ------------------------------------------------------------------


def test_unsubscribe_token_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SESSION_SECRET)
    token = email_module.unsubscribe_token("user-123")
    assert email_module.verify_unsubscribe_token(token) == "user-123"
    assert email_module.verify_unsubscribe_token("garbage") is None


def test_transactional_email_not_gated_on_marketing_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONAR_EMAIL_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("SONAR_EMAIL_TRANSPORT", "log")
    email = email_module.purchase_receipt_email(
        to="buyer@example.com",
        plan_name="Hobby",
        amount="$7",
        renews_at=None,
        cancel_url="https://example.com/pricing",
    )
    assert email.kind == "transactional"
    receipt = email_module.send_email(email)
    assert receipt["transport"] == "log"
