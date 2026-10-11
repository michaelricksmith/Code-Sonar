"""Security event audit log (Phase 5).

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261011_0012"
down_revision = "20261011_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "security_events" in inspector.get_table_names():
        return
    op.create_table(
        "security_events",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128)),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("device_fingerprint", sa.String(64)),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.Text()),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "event_id"),
    )
    op.create_index(
        "ix_security_events_user_time",
        "security_events",
        ["tenant_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "security_events" not in inspector.get_table_names():
        return
    op.drop_index("ix_security_events_user_time", table_name="security_events")
    op.drop_table("security_events")
