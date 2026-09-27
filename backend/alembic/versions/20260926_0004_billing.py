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
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_stripe_customer_id", "users", ["stripe_customer_id"])
    bind = op.get_bind()
    usage_counters.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    usage_counters.drop(bind=bind, checkfirst=True)
    op.drop_constraint("uq_users_stripe_customer_id", "users", type_="unique")
    op.drop_column("users", "stripe_customer_id")
