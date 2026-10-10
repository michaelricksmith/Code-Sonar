"""Migration test: the is_staff column upgrade/downgrade round-trips.

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
PREVIOUS_REVISION = "20260930_0007"
HEAD_REVISION = "20261006_0008"


def _config(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("CODESONAR_DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


def _columns(db_path: Path) -> list[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        return [c["name"] for c in inspector.get_columns("users")]


def test_is_staff_migration_upgrades_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "migration-test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": PREVIOUS_REVISION},
        )

    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "is_staff" in _columns(db_path)

    cfg = _config(db_path, monkeypatch)
    command.downgrade(cfg, PREVIOUS_REVISION)
    assert "is_staff" not in _columns(db_path)

    # And back up again: the migration must be re-runnable.
    cfg = _config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    assert "is_staff" in _columns(db_path)
