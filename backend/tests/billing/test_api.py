"""Tests for the Stripe billing HTTP surface.

No network access: checkout/portal calls patch the Stripe SDK, and webhook
payloads are signed locally with the test webhook secret before being run
through the real ``stripe.Webhook.construct_event``.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import oauth as oauth_module
from app.ask_sonar.runtime import set_scan_provider
from app.billing.plans import PLAN_FREE, PLAN_HOBBY, PLAN_PLUS
from app.billing.usage import get_usage_store
from app.history import ScanRecord
from app.main import app
from app.oauth import OAuthUser, OAuthUserStore, new_session_token, set_oauth_user_store
from app.scan_jobs import set_clone_repo

_TEST_SESSION_SECRET = "billing-test-session-secret"
_TEST_WEBHOOK_SECRET = "whsec_test_billing_secret"
_HOBBY_PRICE = "price_test_hobby"
_PLUS_PRICE = "price_test_plus"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def billing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_billing")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", _TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_PRICE_HOBBY", _HOBBY_PRICE)
    monkeypatch.setenv("STRIPE_PRICE_PLUS", _PLUS_PRICE)


@pytest.fixture
def no_billing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_HOBBY",
        "STRIPE_PRICE_PLUS",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def user_store(tmp_path: Path) -> Generator[tuple[OAuthUserStore, OAuthUser], None, None]:
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth_module.get_oauth_user_store()
    set_oauth_user_store(store)
    user = store.upsert(
        provider="github",
        provider_user_id="4242",
        name="Bill",
        email="bill@example.com",
        avatar_url="",
    )
    yield store, user
    set_oauth_user_store(previous)


@pytest.fixture
def auth_headers(
    user_store: tuple[OAuthUserStore, OAuthUser], monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], OAuthUser]:
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SESSION_SECRET)
    monkeypatch.setattr(oauth_module, "_secret_warning_emitted", True)
    _, user = user_store
    token = new_session_token(user.id, _TEST_SESSION_SECRET)
    return {"Cookie": f"sonar_session={token}"}, user


@pytest.fixture
def fake_clone() -> Generator[None, None, None]:
    def _clone(clone_url: str, branch: str | None, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.py").write_text('"""Fixture."""\n', encoding="utf-8")

    set_clone_repo(_clone)
    yield
    set_clone_repo(None)


def _signed_webhook(event: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(event, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(
        f"{timestamp}.{raw.decode('utf-8')}", _TEST_WEBHOOK_SECRET
    )
    return raw, {"stripe-signature": f"t={timestamp},v1={signature}"}


def _event(event_type: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "evt_test_1",
        "object": "event",
        "type": event_type,
        "data": {"object": obj},
    }


def _scan_record() -> ScanRecord:
    return ScanRecord(
        scan_id="scan-1",
        repository_id="repo-1",
        repository_path="example/repo",
        scanned_at="2026-08-30T20:00:00+00:00",
        schema_version="1.0",
        score=720,
        grade="B",
        total_debt_points=30,
        finding_count=0,
        category_scores={"maintainability": 700},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={"source": 0, "test": 0, "fixture": 0},
        findings=[],
    )


class TestCheckout:
    def test_requires_sign_in(self, client: TestClient, billing_env: None) -> None:
        response = client.post("/api/billing/checkout", json={"tier": "hobby"})
        assert response.status_code == 401

    def test_disabled_without_keys(
        self,
        client: TestClient,
        no_billing_env: None,
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        headers, _ = auth_headers
        response = client.post("/api/billing/checkout", json={"tier": "hobby"}, headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": {"billing_disabled": True}}

    @pytest.mark.parametrize("tier", ["free", "bogus", ""])
    def test_rejects_bad_tier(
        self,
        client: TestClient,
        billing_env: None,
        auth_headers: tuple[dict[str, str], OAuthUser],
        tier: str,
    ) -> None:
        headers, _ = auth_headers
        response = client.post("/api/billing/checkout", json={"tier": tier}, headers=headers)
        assert response.status_code == 400

    def test_creates_session(
        self,
        client: TestClient,
        billing_env: None,
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        headers, user = auth_headers
        fake_session = MagicMock(url="https://checkout.stripe.test/s/abc")
        with patch("stripe.checkout.Session.create", return_value=fake_session) as mock_create:
            response = client.post(
                "/api/billing/checkout",
                json={"tier": "hobby", "autorenew_consent": True},
                headers=headers,
            )
        assert response.status_code == 200
        assert response.json() == {"checkout_url": "https://checkout.stripe.test/s/abc"}
        _, kwargs = mock_create.call_args
        assert kwargs["mode"] == "subscription"
        assert kwargs["client_reference_id"] == user.id
        assert kwargs["line_items"] == [{"price": _HOBBY_PRICE, "quantity": 1}]
        assert kwargs["metadata"] == {"user_id": user.id, "tier": "hobby"}
        assert kwargs["subscription_data"] == {"metadata": {"user_id": user.id}}
        assert kwargs["customer_email"] == "bill@example.com"
        assert kwargs["success_url"].endswith("/app?billing=success")
        assert kwargs["cancel_url"].endswith("/pricing?billing=cancelled")


class TestWebhook:
    def test_disabled_without_keys(self, client: TestClient, no_billing_env: None) -> None:
        raw, headers = _signed_webhook(_event("checkout.session.completed", {}))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": {"billing_disabled": True}}

    def test_bad_signature_is_400(self, client: TestClient, billing_env: None) -> None:
        raw = json.dumps(_event("checkout.session.completed", {})).encode()
        response = client.post(
            "/api/billing/webhook",
            content=raw,
            headers={"stripe-signature": "t=123,v1=deadbeef"},
        )
        assert response.status_code == 400

    def test_webhook_reachable_without_app_auth_in_fail_closed_mode(
        self, client: TestClient, billing_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stripe's servers carry no app session: the webhook must stay
        reachable when the middleware fails closed (production), or no
        subscription would ever activate."""
        monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
        monkeypatch.delenv("CODESONAR_API_TOKEN", raising=False)
        raw = json.dumps(_event("checkout.session.completed", {})).encode()
        response = client.post(
            "/api/billing/webhook",
            content=raw,
            headers={"stripe-signature": "t=123,v1=deadbeef"},
        )
        assert response.status_code == 400
        # ...while authenticated-only routes still fail closed.
        assert client.get("/api/billing/status").status_code == 401

    def test_checkout_completed_sets_plan_and_customer(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
    ) -> None:
        store, user = user_store
        session_obj = {
            "id": "cs_test_1",
            "object": "checkout.session",
            "client_reference_id": user.id,
            "customer": "cus_test_1",
            "metadata": {"user_id": user.id, "tier": "hobby"},
        }
        raw, headers = _signed_webhook(_event("checkout.session.completed", session_obj))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 200
        updated = store.get(user.id)
        assert updated is not None
        assert updated.plan == PLAN_HOBBY
        assert updated.stripe_customer_id == "cus_test_1"

    def test_checkout_completed_resolves_user_from_metadata(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
    ) -> None:
        store, user = user_store
        session_obj = {
            "id": "cs_test_2",
            "object": "checkout.session",
            "client_reference_id": None,
            "customer": "cus_test_2",
            "metadata": {"user_id": user.id, "tier": "plus"},
        }
        raw, headers = _signed_webhook(_event("checkout.session.completed", session_obj))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 200
        updated = store.get(user.id)
        assert updated is not None
        assert updated.plan == PLAN_PLUS

    def test_webhook_is_idempotent(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
    ) -> None:
        store, user = user_store
        session_obj = {
            "id": "cs_test_3",
            "object": "checkout.session",
            "client_reference_id": user.id,
            "customer": "cus_test_3",
            "metadata": {"user_id": user.id, "tier": "hobby"},
        }
        raw, headers = _signed_webhook(_event("checkout.session.completed", session_obj))
        first = client.post("/api/billing/webhook", content=raw, headers=headers)
        second = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        updated = store.get(user.id)
        assert updated is not None
        assert updated.plan == PLAN_HOBBY
        assert updated.stripe_customer_id == "cus_test_3"

    def test_subscription_updated_maps_price_to_plan(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
    ) -> None:
        store, user = user_store
        store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_test_4")
        subscription = {
            "id": "sub_test_1",
            "object": "subscription",
            "customer": "cus_test_4",
            "metadata": {"user_id": user.id},
            "items": {"data": [{"id": "si_1", "price": {"id": _PLUS_PRICE}}]},
        }
        raw, headers = _signed_webhook(_event("customer.subscription.updated", subscription))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 200
        updated = store.get(user.id)
        assert updated is not None
        assert updated.plan == PLAN_PLUS

    def test_subscription_updated_skips_unrecognized_price(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
    ) -> None:
        store, user = user_store
        store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_test_5")
        subscription = {
            "id": "sub_test_2",
            "object": "subscription",
            "customer": "cus_test_5",
            "metadata": {"user_id": user.id},
            "items": {"data": [{"id": "si_2", "price": {"id": "price_unknown"}}]},
        }
        raw, headers = _signed_webhook(_event("customer.subscription.updated", subscription))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 200
        updated = store.get(user.id)
        assert updated is not None
        assert updated.plan == PLAN_HOBBY

    def test_subscription_deleted_downgrades_to_free(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
    ) -> None:
        store, user = user_store
        store.set_billing(user.id, plan=PLAN_PLUS, stripe_customer_id="cus_test_6")
        subscription = {
            "id": "sub_test_3",
            "object": "subscription",
            "customer": "cus_test_6",
            "metadata": {"user_id": user.id},
        }
        raw, headers = _signed_webhook(_event("customer.subscription.deleted", subscription))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 200
        updated = store.get(user.id)
        assert updated is not None
        assert updated.plan == PLAN_FREE
        assert updated.stripe_customer_id == "cus_test_6"

    def test_unknown_event_type_is_200(self, client: TestClient, billing_env: None) -> None:
        raw, headers = _signed_webhook(_event("invoice.paid", {"id": "in_1"}))
        response = client.post("/api/billing/webhook", content=raw, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"received": True}


class TestPortal:
    def test_requires_sign_in(self, client: TestClient, billing_env: None) -> None:
        response = client.post("/api/billing/portal")
        assert response.status_code == 401

    def test_disabled_without_keys(
        self,
        client: TestClient,
        no_billing_env: None,
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        headers, _ = auth_headers
        response = client.post("/api/billing/portal", headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": {"billing_disabled": True}}

    def test_no_customer_is_400(
        self,
        client: TestClient,
        billing_env: None,
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        headers, _ = auth_headers
        response = client.post("/api/billing/portal", headers=headers)
        assert response.status_code == 400

    def test_creates_portal_session(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        store, _ = user_store
        headers, user = auth_headers
        store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_test_7")
        fake_session = MagicMock(url="https://billing.stripe.test/p/abc")
        with patch(
            "stripe.billing_portal.Session.create", return_value=fake_session
        ) as mock_create:
            response = client.post("/api/billing/portal", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"portal_url": "https://billing.stripe.test/p/abc"}
        _, kwargs = mock_create.call_args
        assert kwargs["customer"] == "cus_test_7"


class TestStatus:
    def test_requires_sign_in(self, client: TestClient) -> None:
        assert client.get("/api/billing/status").status_code == 401

    def test_works_when_billing_disabled(
        self,
        client: TestClient,
        no_billing_env: None,
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        headers, _ = auth_headers
        response = client.get("/api/billing/status", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["plan"] == PLAN_FREE
        assert body["limits"]["scans_per_month"] == 5
        assert body["usage"] == {
            "scans_used": 0,
            "ask_sonar_used": 0,
            "period_start": body["usage"]["period_start"],
        }

    def test_reflects_plan_and_usage(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        store, user = user_store
        store.set_billing(user.id, plan=PLAN_PLUS, stripe_customer_id="cus_test_8")
        get_usage_store().increment(user.id, "scans")
        get_usage_store().increment(user.id, "ask_sonar")
        headers, _ = auth_headers
        response = client.get("/api/billing/status", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["plan"] == PLAN_PLUS
        assert body["limits"]["scans_per_month"] == 300
        assert body["usage"]["scans_used"] == 1
        assert body["usage"]["ask_sonar_used"] == 1

    def test_unknown_plan_falls_back_to_free_limits(
        self,
        client: TestClient,
        billing_env: None,
        user_store: tuple[OAuthUserStore, OAuthUser],
        auth_headers: tuple[dict[str, str], OAuthUser],
    ) -> None:
        store, user = user_store
        store.set_billing(user.id, plan="weird-tier", stripe_customer_id="")
        headers, _ = auth_headers
        response = client.get("/api/billing/status", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["plan"] == "weird-tier"
        assert body["limits"]["scans_per_month"] == 5


class TestQuotaWiring:
    def test_scan_job_rejects_when_quota_exceeded(
        self,
        client: TestClient,
        fake_clone: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _deny(user_id: str | None, kind: str) -> None:
            raise HTTPException(status_code=402, detail={"upgrade_required": True})

        monkeypatch.setattr("app.billing.quotas.check_quota", _deny)
        response = client.post("/api/scan-job", json={"repo": "octo/hello"})
        assert response.status_code == 402

    def test_scan_job_records_usage(
        self,
        client: TestClient,
        fake_clone: None,
    ) -> None:
        response = client.post("/api/scan-job", json={"repo": "octo/hello"})
        assert response.status_code == 200
        assert get_usage_store().get_usage(None)["scans_used"] == 1

    def test_ask_sonar_rejects_when_quota_exceeded(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _deny(user_id: str | None, kind: str) -> None:
            raise HTTPException(status_code=402, detail={"upgrade_required": True})

        monkeypatch.setattr("app.billing.quotas.check_quota", _deny)
        response = client.post(
            "/api/ask-sonar/ask",
            json={"scan_id": "scan-1", "question": "Why is my score a B?"},
        )
        assert response.status_code == 402

    def test_ask_sonar_records_usage_after_answer(self, client: TestClient) -> None:
        set_scan_provider(lambda scan_id: _scan_record() if scan_id == "scan-1" else None)
        try:
            response = client.post(
                "/api/ask-sonar/ask",
                json={"scan_id": "scan-1", "question": "Why is my score a B?"},
            )
        finally:
            set_scan_provider(None)
        assert response.status_code == 200
        assert get_usage_store().get_usage(None)["ask_sonar_used"] == 1
