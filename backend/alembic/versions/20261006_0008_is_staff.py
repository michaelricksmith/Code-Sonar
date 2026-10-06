"""Staff flag on users (unlimited testing quota for internal team).

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261006_0008"
down_revision = "20260930_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [col["name"] for col in inspector.get_columns("users")]
    if "is_staff" not in columns:
        op.add_column(
            "users",
            sa.Column("is_staff", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [col["name"] for col in inspector.get_columns("users")]
    if "is_staff" in columns:
        op.drop_column("users", "is_staff")
