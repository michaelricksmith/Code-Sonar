"""Tests for billing plan limits and quota enforcement.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from app import oauth as oauth_module
from app.billing.plans import PLAN_FREE, PLAN_HOBBY, PLAN_PLUS, limits_for
from app.billing.quotas import check_quota
from app.billing.usage import get_usage_store
from app.oauth import OAuthUserStore, set_oauth_user_store


@pytest.fixture
def user_store(tmp_path: Path) -> Generator[OAuthUserStore, None, None]:
    """Swap in an isolated JSON user store."""
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth_module.get_oauth_user_store()
    set_oauth_user_store(store)
    yield store
    set_oauth_user_store(previous)


def _make_user(store: OAuthUserStore, *, plan: str = PLAN_FREE) -> str:
    user = store.upsert(
        provider="github",
        provider_user_id="quota-1",
        name="Quota",
        email="quota@example.com",
        avatar_url="",
    )
    updated = store.set_billing(user.id, plan=plan, stripe_customer_id="")
    assert updated is not None
    return user.id


def _use_up(store_user_id: str | None, kind: str, count: int) -> None:
    store = get_usage_store()
    for _ in range(count):
        store.increment(store_user_id, kind)  # type: ignore[arg-type]


def _detail(excinfo: pytest.ExceptionInfo[HTTPException]) -> dict[str, Any]:
    raw = excinfo.value.detail
    assert isinstance(raw, dict)
    return raw


class TestLimitsFor:
    def test_known_plans(self) -> None:
        assert limits_for(PLAN_FREE)["scans_per_month"] == 5
        assert limits_for(PLAN_HOBBY)["scans_per_month"] == 50
        assert limits_for(PLAN_PLUS)["scans_per_month"] == 300
        assert limits_for(PLAN_PLUS)["history_days"] is None
        assert limits_for(PLAN_PLUS)["priority"] is True
        assert limits_for(PLAN_FREE)["ask_sonar_per_month"] == 25

    def test_unknown_plan_falls_back_to_free(self) -> None:
        assert limits_for("enterprise") == limits_for(PLAN_FREE)
        assert limits_for("") == limits_for(PLAN_FREE)
        assert limits_for(None) == limits_for(PLAN_FREE)

    def test_returns_a_copy(self) -> None:
        limits_for(PLAN_FREE)["scans_per_month"] = 999
        assert limits_for(PLAN_FREE)["scans_per_month"] == 5


class TestCheckQuota:
    def test_under_limit_passes(self, user_store: OAuthUserStore) -> None:
        user_id = _make_user(user_store)
        _use_up(user_id, "scans", 4)
        check_quota(user_id, "scans")  # 4 < 5: no raise

    def test_at_limit_raises_402(self, user_store: OAuthUserStore) -> None:
        user_id = _make_user(user_store)
        _use_up(user_id, "scans", 5)
        with pytest.raises(HTTPException) as excinfo:
            check_quota(user_id, "scans")
        assert excinfo.value.status_code == 402
        detail = _detail(excinfo)
        assert detail["upgrade_required"] is True
        assert detail["kind"] == "scans"
        assert detail["plan"] == PLAN_FREE
        assert detail["limit"] == 5
        assert detail["used"] == 5

    def test_over_limit_raises_402(self, user_store: OAuthUserStore) -> None:
        user_id = _make_user(user_store)
        _use_up(user_id, "ask_sonar", 30)
        with pytest.raises(HTTPException) as excinfo:
            check_quota(user_id, "ask_sonar")
        assert excinfo.value.status_code == 402
        assert _detail(excinfo)["limit"] == 25
        assert _detail(excinfo)["used"] == 30

    def test_paid_plan_gets_paid_limits(self, user_store: OAuthUserStore) -> None:
        user_id = _make_user(user_store, plan=PLAN_HOBBY)
        _use_up(user_id, "scans", 5)
        check_quota(user_id, "scans")  # 5 < 50: no raise

    def test_anonymous_user_gets_free_limits(self) -> None:
        _use_up(None, "scans", 5)
        with pytest.raises(HTTPException) as excinfo:
            check_quota(None, "scans")
        assert excinfo.value.status_code == 402
        assert _detail(excinfo)["plan"] == PLAN_FREE

    def test_unknown_user_id_gets_free_limits(self) -> None:
        check_quota("no-such-user", "scans")  # no usage, no user: passes

    def test_unknown_plan_string_gets_free_limits(self, user_store: OAuthUserStore) -> None:
        user_id = _make_user(user_store, plan="mystery-tier")
        _use_up(user_id, "scans", 5)
        with pytest.raises(HTTPException) as excinfo:
            check_quota(user_id, "scans")
        assert _detail(excinfo)["plan"] == "mystery-tier"
        assert _detail(excinfo)["limit"] == 5
