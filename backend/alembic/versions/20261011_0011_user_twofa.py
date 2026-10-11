"""Two-factor authentication storage (TOTP secrets + backup codes).

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261011_0011"
down_revision = "20261011_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_twofa" in inspector.get_table_names():
        return
    op.create_table(
        "user_twofa",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("enrolled_at", sa.String(64)),
        sa.Column("backup_codes_json", sa.Text()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_twofa" not in inspector.get_table_names():
        return
    op.drop_table("user_twofa")
