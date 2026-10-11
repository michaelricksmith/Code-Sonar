"""Migration test: the email_preferences table upgrade/downgrade round-trips.

Runs the real Alembic scripts against a scratch SQLite database so a
broken migration is caught here instead of at deploy time.

Copyright \u00a9 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"
PREVIOUS_REVISION = "20261011_0009"
HEAD_REVISION = "20261011_0010"


def _sqlite_url(db_path: Path) -> str:
    return "sqlite:" + "/" * 3 + str(db_path)


def _config(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("CODESONAR_DATABASE_URL", _sqlite_url(db_path))
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


def _tables(db_path: Path) -> list[str]:
    engine = sa.create_engine(_sqlite_url(db_path))
    with engine.connect() as conn:
        return sa.inspect(conn).get_table_names()


def test_email_preferences_migration_upgrades_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "migration-test.db"
    engine = sa.create_engine(_sqlite_url(db_path))
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE tenants (tenant_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": PREVIOUS_REVISION},
        )

    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "email_preferences" in _tables(db_path)

    # The migration must be idempotent: upgrading twice is a no-op.
    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "email_preferences" in _tables(db_path)

    cfg = _config(db_path, monkeypatch)
    command.downgrade(cfg, PREVIOUS_REVISION)
    assert "email_preferences" not in _tables(db_path)

    # And back up again.
    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "email_preferences" in _tables(db_path)

    with engine.connect() as conn:
        columns = [c["name"] for c in sa.inspect(conn).get_columns("email_preferences")]
    for expected in ("tenant_id", "user_id", "digest_enabled", "unsubscribed_at"):
        assert expected in columns
