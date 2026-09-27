"""Stripe billing: users.stripe_customer_id + usage_counters table.

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op
from app.billing.tables import usage_counters

revision = "20260926_0004"
down_revision = "20260926_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {col["name"] for col in sa.inspect(bind).get_columns("users")}
    if "stripe_customer_id" not in existing:
        # Fresh databases already carry the column: 20260926_0003 creates
        # ``users`` from the live Table definition, which now includes it.
        # Batch mode keeps this portable — SQLite cannot ADD CONSTRAINT via
        # plain ALTER (on PostgreSQL batch issues the plain ALTERs directly).
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("stripe_customer_id", sa.String(255), nullable=True))
            batch_op.create_unique_constraint(
                "uq_users_stripe_customer_id", ["stripe_customer_id"]
            )
    usage_counters.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    usage_counters.drop(bind=bind, checkfirst=True)
    existing = {col["name"] for col in sa.inspect(bind).get_columns("users")}
    if "stripe_customer_id" not in existing:
        return
    names = {c["name"] for c in sa.inspect(bind).get_unique_constraints("users")}
    if "uq_users_stripe_customer_id" in names:
        op.drop_constraint("uq_users_stripe_customer_id", "users", type_="unique")
    # Batch rebuild: SQLite cannot DROP COLUMN while an inline UNIQUE (fresh
    # DBs) references it; batch mode recreates the table cleanly on all dialects.
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("stripe_customer_id")
