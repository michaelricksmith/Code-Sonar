"""Scanned commit SHA on scan records.

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0006"
down_revision = "20260927_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: the baseline migration creates tables from current
    # metadata, so fresh databases already have this column.
    inspector = sa.inspect(op.get_bind())
    columns = [col["name"] for col in inspector.get_columns("scans")]
    if "commit_sha" not in columns:
        op.add_column("scans", sa.Column("commit_sha", sa.String(64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [col["name"] for col in inspector.get_columns("scans")]
    if "commit_sha" in columns:
        op.drop_column("scans", "commit_sha")
