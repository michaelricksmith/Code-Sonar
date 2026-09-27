"""Billing persistence tables on the shared SQLAlchemy metadata.

``usage_counters`` has no hard foreign key to ``users`` on purpose: the
"anonymous" sentinel id (used for signed-out callers) has no user row, and
counters must still be recorded for it.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, Table, UniqueConstraint

from app.persistence.schema import metadata

usage_counters = Table(
    "usage_counters",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", String(64), nullable=False, index=True),
    # First day of the UTC month the counters belong to, YYYY-MM-DD.
    Column("period_start", String(10), nullable=False),
    Column("scans_used", Integer, nullable=False, default=0),
    Column("ask_sonar_used", Integer, nullable=False, default=0),
    UniqueConstraint("user_id", "period_start", name="uq_usage_counters_user_period"),
)
