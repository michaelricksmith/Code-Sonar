"""Durable fix tracking: fix_attempts table for prompt-first remediation.

Copyright © 2026 Michael Smith. All rights reserved.

Replaces the ephemeral ``~/.code-sonar/prompt-events.jsonl`` file with a
tenant-scoped Postgres table. Each row records one copied fix prompt with
the user who copied it; ``verified_at`` is set when a later rescan shows
the finding is gone. This table is the raw material for per-user fix
stats, streaks, and the weekly digest.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261011_0009"
down_revision = "20261006_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "fix_attempts" in inspector.get_table_names():
        return
    op.create_table(
        "fix_attempts",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("repository_id", sa.String(128), nullable=False),
        sa.Column("scan_id", sa.String(128)),
        sa.Column("finding_id", sa.String(255), nullable=False),
        sa.Column("rule_id", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("copied_at", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.String(64)),
        sa.Column("verified_scan_id", sa.String(128)),
        sa.Column("score_delta", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "attempt_id"),
    )
    op.create_index(
        "ix_fix_attempts_user_verified",
        "fix_attempts",
        ["tenant_id", "user_id", "verified_at"],
    )
    op.create_index(
        "ix_fix_attempts_repo",
        "fix_attempts",
        ["tenant_id", "repository_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "fix_attempts" not in inspector.get_table_names():
        return
    op.drop_index("ix_fix_attempts_repo", table_name="fix_attempts")
    op.drop_index("ix_fix_attempts_user_verified", table_name="fix_attempts")
    op.drop_table("fix_attempts")
