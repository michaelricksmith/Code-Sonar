"""SQLAlchemy Core schema with tenant-aware keys and relationships."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

tenants = Table("tenants", metadata, Column("tenant_id", String(128), primary_key=True))


def _tenant_table(name: str, id_name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("tenant_id", String(128), primary_key=True),
        Column(id_name, String(128), primary_key=True),
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
    )


projects = _tenant_table("projects", "project_id")
for column in (
    Column("provider", String(32), nullable=False),
    Column("owner", String(255), nullable=False),
    Column("name", String(255), nullable=False),
    Column("default_branch", String(255), nullable=False),
    Column("connected_at", String(64), nullable=False),
    Column("checkout_path_ciphertext", Text, nullable=False),
    Column("encryption_provider", String(64), nullable=False),
    Column("latest_scan_id", String(128)),
    Column("latest_score", Integer),
    Column("provider_repository_id", Integer),
    Column("provider_installation_id", Integer),
):
    projects.append_column(column)

scans = _tenant_table("scans", "scan_id")
for column in (
    Column("repository_id", String(128), nullable=False),
    Column("repository_path", Text, nullable=False),
    Column("scanned_at", String(64), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("scoring_version", String(32), nullable=False),
    Column("score", Integer, nullable=False),
    Column("grade", String(8), nullable=False),
    Column("total_debt_points", Integer, nullable=False),
    Column("finding_count", Integer, nullable=False),
    Column("aggregates", JSON, nullable=False),
):
    scans.append_column(column)
Index(
    "ix_scans_tenant_repository_time", scans.c.tenant_id, scans.c.repository_id, scans.c.scanned_at
)

findings = _tenant_table("findings", "finding_row_id")
findings.append_column(Column("scan_id", String(128), nullable=False))
findings.append_column(Column("finding_id", String(255), nullable=False))
findings.append_column(Column("ordinal", Integer, nullable=False))
findings.append_column(Column("payload", JSON, nullable=False))
findings.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "scan_id"], ["scans.tenant_id", "scans.scan_id"], ondelete="CASCADE"
    )
)
findings.append_constraint(UniqueConstraint("tenant_id", "scan_id", "finding_id"))
findings.append_constraint(UniqueConstraint("tenant_id", "scan_id", "ordinal"))

github_installations = _tenant_table("github_installations", "installation_id")
for column in (
    Column("account_login", String(255), nullable=False),
    Column("account_type", String(64), nullable=False),
    Column("installed_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("repository_selection", String(32), nullable=False),
):
    github_installations.append_column(column)

webhook_deliveries = _tenant_table("webhook_deliveries", "delivery_id")
webhook_deliveries.append_column(Column("payload", JSON, nullable=False))

webhook_jobs = _tenant_table("webhook_jobs", "job_id")
for column in (
    Column("delivery_id", String(128), nullable=False),
    Column("project_id", String(128), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("state", String(32), nullable=False),
    Column("lease_owner", String(128)),
    Column("lease_expires_at", String(64)),
):
    webhook_jobs.append_column(column)
webhook_jobs.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "delivery_id"],
        ["webhook_deliveries.tenant_id", "webhook_deliveries.delivery_id"],
        ondelete="CASCADE",
    )
)
webhook_jobs.append_constraint(
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        ["projects.tenant_id", "projects.project_id"],
        ondelete="CASCADE",
    )
)

remediation_outcomes = _tenant_table("remediation_outcomes", "outcome_id")
remediation_outcomes.append_column(Column("repository_id", String(128), nullable=False))
remediation_outcomes.append_column(Column("before_scan_id", String(128), nullable=False))
remediation_outcomes.append_column(Column("after_scan_id", String(128), nullable=False))
remediation_outcomes.append_column(Column("payload", JSON, nullable=False))
for scan_column in ("before_scan_id", "after_scan_id"):
    remediation_outcomes.append_constraint(
        ForeignKeyConstraint(
            ["tenant_id", scan_column],
            ["scans.tenant_id", "scans.scan_id"],
            ondelete="RESTRICT",
        )
    )

migration_ledger = Table(
    "migration_ledger",
    metadata,
    Column("import_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("source_path", Text, nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("imported_at", String(64), nullable=False),
    ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
    UniqueConstraint("tenant_id", "source_sha256"),
)
