"""Email/password authentication columns on users.

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261011_0014"
down_revision = "20261011_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "password_hash" not in existing:
            batch_op.add_column(sa.Column("password_hash", sa.Text()))
        if "email_verified" not in existing:
            batch_op.add_column(
                sa.Column("email_verified", sa.Boolean(), server_default="0")
            )
        if "email_verify_token_hash" not in existing:
            batch_op.add_column(sa.Column("email_verify_token_hash", sa.String(64)))
        if "password_reset_token_hash" not in existing:
            batch_op.add_column(sa.Column("password_reset_token_hash", sa.String(64)))
        if "password_reset_expires_at" not in existing:
            batch_op.add_column(sa.Column("password_reset_expires_at", sa.String(64)))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return
    with op.batch_alter_table("users") as batch_op:
        for column in (
            "password_reset_expires_at",
            "password_reset_token_hash",
            "email_verify_token_hash",
            "email_verified",
            "password_hash",
        ):
            try:
                batch_op.drop_column(column)
            except Exception:
                pass
