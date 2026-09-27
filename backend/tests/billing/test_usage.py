"""Tests for the monthly usage counters (SQL backend + JSON fallback).

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.billing import usage as usage_module
from app.billing.tables import usage_counters  # noqa: F401 - registers table on metadata
from app.billing.usage import (
    ANONYMOUS_USER_ID,
    UsageStore,
    current_period_start,
)
from app.persistence.schema import metadata


@pytest.fixture
def json_store(tmp_path: Path) -> UsageStore:
    return UsageStore(path=tmp_path / "usage-counters.json")


@pytest.fixture
def sql_store(tmp_path: Path) -> UsageStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'usage.db'}")
    metadata.create_all(engine)
    return UsageStore(engine=engine)


@pytest.fixture(params=["json_store", "sql_store"])
def any_store(request: pytest.FixtureRequest) -> UsageStore:
    return request.getfixturevalue(request.param)  # type: ignore[no-any-return]


class TestUsageCounters:
    def test_fresh_usage_is_zeros(self, any_store: UsageStore) -> None:
        usage = any_store.get_usage("user-1")
        assert usage == {
            "user_id": "user-1",
            "period_start": current_period_start(),
            "scans_used": 0,
            "ask_sonar_used": 0,
        }

    def test_increment_scans(self, any_store: UsageStore) -> None:
        any_store.increment("user-1", "scans")
        any_store.increment("user-1", "scans")
        usage = any_store.get_usage("user-1")
        assert usage["scans_used"] == 2
        assert usage["ask_sonar_used"] == 0

    def test_increment_ask_sonar(self, any_store: UsageStore) -> None:
        result = any_store.increment("user-1", "ask_sonar")
        assert result["ask_sonar_used"] == 1
        assert result["scans_used"] == 0

    def test_counters_are_per_user(self, any_store: UsageStore) -> None:
        any_store.increment("user-1", "scans")
        assert any_store.get_usage("user-2")["scans_used"] == 0

    def test_anonymous_sentinel(self, any_store: UsageStore) -> None:
        any_store.increment(None, "scans")
        assert any_store.get_usage(None)["scans_used"] == 1
        assert any_store.get_usage(ANONYMOUS_USER_ID)["scans_used"] == 1

    def test_invalid_kind_rejected(self, any_store: UsageStore) -> None:
        with pytest.raises(ValueError):
            any_store.increment("user-1", "fix_prompts")  # type: ignore[arg-type]

    def test_period_rollover_resets_counters(
        self, any_store: UsageStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(usage_module, "current_period_start", lambda: "2020-01-01")
        any_store.increment("user-1", "scans")
        assert any_store.get_usage("user-1")["scans_used"] == 1
        # Back in the real current month the old row is ignored: fresh zeros.
        monkeypatch.undo()
        usage = any_store.get_usage("user-1")
        assert usage["scans_used"] == 0
        assert usage["period_start"] == current_period_start()

    def test_json_file_is_mode_0600(self, json_store: UsageStore, tmp_path: Path) -> None:
        json_store.increment("user-1", "scans")
        path = tmp_path / "usage-counters.json"
        assert path.exists()
        assert (path.stat().st_mode & 0o777) == 0o600
