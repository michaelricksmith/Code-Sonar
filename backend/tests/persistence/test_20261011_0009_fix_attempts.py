"""Migration test: the fix_attempts table upgrade/downgrade round-trips.

Runs the real Alembic scripts against a scratch SQLite database so a
broken migration is caught here instead of at deploy time.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"
PREVIOUS_REVISION = "20261006_0008"
HEAD_REVISION = "20261011_0009"


def _config(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("CODESONAR_DATABASE_URL", "sqlite:" + "/" * 3 + str(db_path))
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


def _tables(db_path: Path) -> list[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        return sa.inspect(conn).get_table_names()


def test_fix_attempts_migration_upgrades_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "migration-test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE tenants (tenant_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": PREVIOUS_REVISION},
        )

    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "fix_attempts" in _tables(db_path)

    # The migration must be idempotent: upgrading twice is a no-op.
    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "fix_attempts" in _tables(db_path)

    cfg = _config(db_path, monkeypatch)
    command.downgrade(cfg, PREVIOUS_REVISION)
    assert "fix_attempts" not in _tables(db_path)

    # And back up again.
    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "fix_attempts" in _tables(db_path)

    with engine.connect() as conn:
        columns = [c["name"] for c in sa.inspect(conn).get_columns("fix_attempts")]
    for expected in (
        "tenant_id", "attempt_id", "user_id", "repository_id", "finding_id",
        "rule_id", "file_path", "copied_at", "verified_at", "verified_scan_id",
        "score_delta",
    ):
        assert expected in columns
