"""Server-side sessions with short-lived access tokens (Phase 6).

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261011_0013"
down_revision = "20261011_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_sessions" in inspector.get_table_names():
        return
    op.create_table(
        "user_sessions",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("device_info", sa.String(512)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("last_seen_at", sa.String(64)),
        sa.Column("expires_at", sa.String(64), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "session_id"),
    )
    op.create_index(
        "ix_user_sessions_user",
        "user_sessions",
        ["tenant_id", "user_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_sessions" not in inspector.get_table_names():
        return
    op.drop_index("ix_user_sessions_user", table_name="user_sessions")
    op.drop_table("user_sessions")
