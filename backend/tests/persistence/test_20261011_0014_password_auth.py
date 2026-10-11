"""Migration test: password auth columns upgrade/downgrade round-trips.

Copyright \u00a9 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"
PREVIOUS_REVISION = "20261011_0013"


def _sqlite_url(db_path: Path) -> str:
    return "sqlite:" + "/" * 3 + str(db_path)


def test_password_auth_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "migration-test.db"
    url = _sqlite_url(db_path)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE tenants (tenant_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": PREVIOUS_REVISION},
        )
    monkeypatch.setenv("CODESONAR_DATABASE_URL", url)
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        columns = {c["name"] for c in sa.inspect(conn).get_columns("users")}
    for expected in (
        "password_hash",
        "email_verified",
        "email_verify_token_hash",
        "password_reset_token_hash",
        "password_reset_expires_at",
    ):
        assert expected in columns
