"""Operational privacy records and job contracts."""

from alembic import op

from app.persistence.schema import (
    deletion_receipts,
    privacy_audit_events,
    privacy_jobs,
    tenant_lifecycle,
    tenant_retention_policies,
)

revision = "20260902_0002"
down_revision = "20260902_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in (
        tenant_retention_policies,
        tenant_lifecycle,
        privacy_jobs,
        privacy_audit_events,
        deletion_receipts,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        deletion_receipts,
        privacy_audit_events,
        privacy_jobs,
        tenant_lifecycle,
        tenant_retention_policies,
    ):
        table.drop(bind=bind, checkfirst=True)
