"""SQL tests for ``SqlFixAttemptStore`` against sqlite + the real schema.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from app.fix_tracking.models import FixAttempt
from app.persistence.repositories import SqlFixAttemptStore
from app.persistence.schema import metadata
from app.security.tenant import bind_tenant, reset_tenant

TENANT = "tenant-a"


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine, None, None]:
    token = bind_tenant(TENANT)
    eng = create_engine(f"sqlite:///{tmp_path / 'fix.db'}")
    metadata.create_all(eng)
    yield eng
    reset_tenant(token)
    eng.dispose()


def _attempt(**overrides: object) -> FixAttempt:
    data: dict[str, object] = {
        "attempt_id": "attempt-1",
        "user_id": "user-1",
        "repository_id": "repo-1",
        "finding_id": "finding-1",
        "rule_id": "test:rule",
        "file_path": "src/app.py",
        "copied_at": "2026-01-01T00:00:00+00:00",
        "scan_id": "scan-1",
    }
    data.update(overrides)
    return FixAttempt.from_dict(data)


class TestSqlFixAttemptStore:
    def test_round_trip(self, engine: Engine) -> None:
        store = SqlFixAttemptStore(engine)
        store.append(_attempt())
        (loaded,) = store.list_by_user("user-1")
        assert loaded.attempt_id == "attempt-1"
        assert loaded.rule_id == "test:rule"
        assert loaded.scan_id == "scan-1"
        assert not loaded.verified

    def test_list_open_and_mark_verified(self, engine: Engine) -> None:
        store = SqlFixAttemptStore(engine)
        store.append(_attempt(attempt_id="a1"))
        store.append(_attempt(attempt_id="a2", finding_id="finding-2"))
        assert [a.attempt_id for a in store.list_open("repo-1")] == ["a1", "a2"]
        assert store.mark_verified(
            "a1",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-2",
            score_delta=25,
        )
        assert [a.attempt_id for a in store.list_open("repo-1")] == ["a2"]
        (verified,) = store.list_by_user("user-1", verified_only=True)
        assert verified.attempt_id == "a1"
        assert verified.score_delta == 25
        assert verified.verified_scan_id == "scan-2"

    def test_mark_verified_idempotent(self, engine: Engine) -> None:
        store = SqlFixAttemptStore(engine)
        store.append(_attempt())
        assert store.mark_verified(
            "attempt-1",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-2",
            score_delta=None,
        )
        assert not store.mark_verified(
            "attempt-1",
            verified_at="2026-06-02T00:00:00+00:00",
            verified_scan_id="scan-3",
            score_delta=None,
        )

    def test_tenant_isolation(self, engine: Engine) -> None:
        store = SqlFixAttemptStore(engine)
        store.append(_attempt())
        token = bind_tenant("tenant-b")
        try:
            assert store.list_by_user("user-1") == []
            assert store.list_open("repo-1") == []
        finally:
            reset_tenant(token)

    def test_duplicate_attempt_rejected(self, engine: Engine) -> None:
        store = SqlFixAttemptStore(engine)
        store.append(_attempt())
        with pytest.raises(FileExistsError):
            store.append(_attempt())
