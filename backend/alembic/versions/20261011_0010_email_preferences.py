"""Weekly digest email preferences.

Copyright © 2026 Michael Smith. All rights reserved.

One row per user. Users are opted in by default; one-tap unsubscribe
sets ``digest_enabled`` to false with a timestamp. No email is ever sent
to a user with ``digest_enabled`` false.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261011_0010"
down_revision = "20261011_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "email_preferences" in inspector.get_table_names():
        return
    op.create_table(
        "email_preferences",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("unsubscribed_at", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "email_preferences" not in inspector.get_table_names():
        return
    op.drop_table("email_preferences")
