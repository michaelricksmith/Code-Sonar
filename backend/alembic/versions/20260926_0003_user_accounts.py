"""Database-backed user accounts (replaces oauth-users.json).

Copyright © 2026 Michael Smith. All rights reserved.
"""

from alembic import op
from app.models.user import users

revision = "20260926_0003"
down_revision = "20260902_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    users.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    users.drop(bind=bind, checkfirst=True)
