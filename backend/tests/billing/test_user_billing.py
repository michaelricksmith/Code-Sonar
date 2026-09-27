"""Tests for UserStore billing support (plan + Stripe customer id).

Covers the JSON ``OAuthUserStore`` and the SQL ``SqlUserStore``.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.billing.plans import PLAN_FREE, PLAN_HOBBY
from app.models.user import users  # noqa: F401 - registers table on metadata
from app.oauth import OAuthUser, OAuthUserStore
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.repositories import SqlUserStore
from app.persistence.schema import metadata


def _oauth_user() -> OAuthUser:
    return OAuthUser(
        id="user-billing-1",
        provider="github",
        provider_user_id="4242",
        name="Bill",
        email="bill@example.com",
        avatar_url="",
    )


@pytest.fixture
def json_store(tmp_path: Path) -> OAuthUserStore:
    return OAuthUserStore(path=tmp_path / "oauth-users.json")


@pytest.fixture
def sql_store(tmp_path: Path) -> SqlUserStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}")
    metadata.create_all(engine)
    return SqlUserStore(engine, LocalDevelopmentEncryptionProvider(b"k" * 32))


def _seed_json(store: OAuthUserStore) -> OAuthUser:
    return store.upsert(
        provider="github",
        provider_user_id="4242",
        name="Bill",
        email="bill@example.com",
        avatar_url="",
    )


def _seed_sql(store: SqlUserStore) -> OAuthUser:
    return store.upsert(
        provider="github",
        provider_user_id="4242",
        name="Bill",
        email="bill@example.com",
        avatar_url="",
    )


class TestJsonUserStoreBilling:
    def test_new_user_defaults(self, json_store: OAuthUserStore) -> None:
        user = _seed_json(json_store)
        assert user.plan == PLAN_FREE
        assert user.stripe_customer_id == ""

    def test_set_billing_updates_plan_and_customer(self, json_store: OAuthUserStore) -> None:
        user = _seed_json(json_store)
        updated = json_store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_123")
        assert updated is not None
        assert updated.plan == PLAN_HOBBY
        assert updated.stripe_customer_id == "cus_123"
        assert json_store.get(user.id) is not None
        reloaded = json_store.get(user.id)
        assert reloaded is not None
        assert reloaded.plan == PLAN_HOBBY
        assert reloaded.stripe_customer_id == "cus_123"

    def test_set_billing_empty_customer_preserves_existing(
        self, json_store: OAuthUserStore
    ) -> None:
        user = _seed_json(json_store)
        json_store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_123")
        updated = json_store.set_billing(user.id, plan=PLAN_FREE, stripe_customer_id="")
        assert updated is not None
        assert updated.plan == PLAN_FREE
        assert updated.stripe_customer_id == "cus_123"

    def test_set_billing_unknown_user_returns_none(self, json_store: OAuthUserStore) -> None:
        assert (
            json_store.set_billing("no-such-user", plan=PLAN_HOBBY, stripe_customer_id="") is None
        )

    def test_upsert_does_not_clobber_billing(self, json_store: OAuthUserStore) -> None:
        user = _seed_json(json_store)
        json_store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_123")
        relogin = json_store.upsert(
            provider="github",
            provider_user_id="4242",
            name="Bill Renamed",
            email="bill@example.com",
            avatar_url="",
        )
        assert relogin.plan == PLAN_HOBBY
        assert relogin.stripe_customer_id == "cus_123"
        assert relogin.name == "Bill Renamed"


class TestSqlUserStoreBilling:
    def test_new_user_defaults(self, sql_store: SqlUserStore) -> None:
        user = _seed_sql(sql_store)
        assert user.plan == PLAN_FREE
        assert user.stripe_customer_id == ""

    def test_set_billing_updates_plan_and_customer(self, sql_store: SqlUserStore) -> None:
        user = _seed_sql(sql_store)
        updated = sql_store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_123")
        assert updated is not None
        assert updated.plan == PLAN_HOBBY
        assert updated.stripe_customer_id == "cus_123"
        reloaded = sql_store.get(user.id)
        assert reloaded is not None
        assert reloaded.plan == PLAN_HOBBY
        assert reloaded.stripe_customer_id == "cus_123"

    def test_set_billing_empty_customer_preserves_existing(self, sql_store: SqlUserStore) -> None:
        user = _seed_sql(sql_store)
        sql_store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_123")
        updated = sql_store.set_billing(user.id, plan=PLAN_FREE, stripe_customer_id="")
        assert updated is not None
        assert updated.plan == PLAN_FREE
        assert updated.stripe_customer_id == "cus_123"

    def test_set_billing_unknown_user_returns_none(self, sql_store: SqlUserStore) -> None:
        assert sql_store.set_billing("no-such-user", plan=PLAN_HOBBY, stripe_customer_id="") is None

    def test_upsert_does_not_clobber_plan(self, sql_store: SqlUserStore) -> None:
        user = _seed_sql(sql_store)
        sql_store.set_billing(user.id, plan=PLAN_HOBBY, stripe_customer_id="cus_123")
        relogin = sql_store.upsert(
            provider="github",
            provider_user_id="4242",
            name="Bill",
            email="bill@example.com",
            avatar_url="",
        )
        assert relogin.plan == PLAN_HOBBY
        assert relogin.stripe_customer_id == "cus_123"
