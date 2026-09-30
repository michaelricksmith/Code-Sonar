"""Cross-worker rate-limit hits table.

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0007"
down_revision = "20260930_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: the baseline migration creates tables from current
    # metadata, so fresh databases already have this table.
    inspector = sa.inspect(op.get_bind())
    if "rate_limit_hits" not in inspector.get_table_names():
        op.create_table(
            "rate_limit_hits",
            sa.Column("hit_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("bucket_key", sa.String(255), nullable=False),
            sa.Column("hit_at", sa.Float(), nullable=False),
        )
    indexes = [idx["name"] for idx in inspector.get_indexes("rate_limit_hits")]
    if "ix_rate_limit_hits_bucket_time" not in indexes:
        op.create_index(
            "ix_rate_limit_hits_bucket_time", "rate_limit_hits", ["bucket_key", "hit_at"]
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "rate_limit_hits" in inspector.get_table_names():
        indexes = [idx["name"] for idx in inspector.get_indexes("rate_limit_hits")]
        if "ix_rate_limit_hits_bucket_time" in indexes:
            op.drop_index("ix_rate_limit_hits_bucket_time", table_name="rate_limit_hits")
        op.drop_table("rate_limit_hits")
