"""User accounts — SQLAlchemy Core table on the shared persistence metadata.

This module is imported for its side effect (registering the ``users`` table
on the shared ``MetaData``) by ``app.persistence.runtime`` and
``backend/alembic/env.py``. It is intentionally *not* imported by
``app.persistence.schema``: that module only defines ``metadata`` at import
time, and importing this module from it would create a circular import.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, String, Table, Text

from app.persistence.schema import metadata

# Account lifecycle states.
STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"

# Billing plans.
PLAN_FREE = "free"

# Provider keys used in the ``provider`` column and OAuth callbacks.
PROVIDER_GITHUB = "github"
PROVIDER_GOOGLE = "google"

users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    # Normalized (trimmed, lower-cased) email; NULL when the provider
    # supplies none. Unique where present so one email maps to one account
    # even across providers.
    Column("email", String(320), unique=True),
    Column("display_name", String(255), nullable=False, default=""),
    Column("avatar_url", String(1024), nullable=False, default=""),
    # Provider identities. A user may link both GitHub and Google to one
    # account; each external identity is globally unique where present.
    Column("github_id", String(64), unique=True),
    Column("github_username", String(255)),
    Column("google_sub", String(255), unique=True),
    # Most recently used provider (display/back-compat only; identity
    # columns are authoritative for login matching).
    Column("provider", String(32), nullable=False, default=""),
    Column("plan", String(32), nullable=False, default=PLAN_FREE),
    Column("status", String(32), nullable=False, default=STATUS_ACTIVE),
    Column("is_admin", Boolean, nullable=False, default=False),
    # OAuth tokens are encrypted at rest; see app.persistence.crypto.
    Column("github_token_ciphertext", Text),
    # ISO-8601 timestamps, matching the rest of the persistence schema.
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("last_login_at", String(64)),
)
