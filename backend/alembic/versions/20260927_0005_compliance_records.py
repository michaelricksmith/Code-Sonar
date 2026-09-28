"""Pre-launch compliance records table (auto-renewal consent, cancellations,
marketing consent, age-gate confirmations, GPC opt-outs, reminder history).

Copyright © 2026 Michael Smith. All rights reserved.
"""

import sqlalchemy as sa

from alembic import op
from app.persistence.schema import compliance_records

revision = "20260927_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    compliance_records.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    compliance_records.drop(op.get_bind(), checkfirst=True)
