"""Runtime wiring for the transactional persistence unit of work."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text, update

from app.billing.tables import (
    usage_counters as usage_counters_table,  # noqa: F401 - registers table on metadata
)
from app.history import ScanRecord
from app.models.user import users as users_table  # noqa: F401 - registers table on metadata
from app.persistence.config import (
    PersistenceConfig,
    persistence_config_from_env,
    psycopg3_database_url,
    secure_data_file,
    validate_persistence_config,
)
from app.persistence.crypto import (
    EncryptionProvider,
    EnvKeyEncryptionProvider,
    LocalDevelopmentEncryptionProvider,
)
from app.persistence.privacy import CryptoErasureHook, SqlPrivacyRepository
from app.persistence.repositories import (
    SqlComplianceRecordStore,
    SqlGitHubInstallationStore,
    SqlHistoryStore,
    SqlOutcomeStore,
    SqlProjectStore,
    SqlUserStore,
    SqlWebhookAuditStore,
    SqlWebhookScanJobStore,
)
from app.persistence.schema import (  # noqa: F401 - registers table on metadata
    compliance_records,
    metadata,
    projects,
)
from app.security.runtime import local_dev_enabled
from app.security.tenant import current_tenant_id

logger = logging.getLogger(__name__)


@dataclass
class PersistenceUnitOfWork:
    """Own the engine and cross-repository atomic operations."""

    engine: Engine
    encryption: EncryptionProvider
    crypto_erasure: CryptoErasureHook | None = None

    def __post_init__(self) -> None:
        self.history = SqlHistoryStore(self.engine)
        self.projects = SqlProjectStore(self.engine, self.encryption)
        self.installations = SqlGitHubInstallationStore(self.engine)
        self.webhook_audit = SqlWebhookAuditStore(self.engine)
        self.webhook_jobs = SqlWebhookScanJobStore(self.engine)
        self.outcomes = SqlOutcomeStore(self.engine)
        self.users = SqlUserStore(self.engine, self.encryption)
        self.privacy = SqlPrivacyRepository(self.engine, self.encryption, self.crypto_erasure)
        self.compliance = SqlComplianceRecordStore(self.engine)

    def record_project_scan(self, project_id: str, record: ScanRecord) -> None:
        """Persist scan/findings and advance project baseline in one transaction."""
        with self.engine.begin() as connection:
            self.history._append(connection, record)
            changed = connection.execute(
                update(projects)
                .where(
                    projects.c.tenant_id == current_tenant_id(),
                    projects.c.project_id == project_id,
                )
                .values(latest_scan_id=record.scan_id, latest_score=record.score)
            )
            if changed.rowcount != 1:
                raise LookupError("Project not found")


_persistence: PersistenceUnitOfWork | None = None
_external_encryption_provider: EncryptionProvider | None = None


def set_external_encryption_provider(provider: EncryptionProvider | None) -> None:
    """Inject a deployment-owned KMS/envelope provider before startup."""
    global _external_encryption_provider
    _external_encryption_provider = provider


def production_encryption_provider_available(provider_name: str) -> bool:
    """Report whether startup can resolve the named production-safe provider."""
    return bool(
        provider_name
        and _external_encryption_provider is not None
        and _external_encryption_provider.production_safe
        and provider_name == _external_encryption_provider.provider_name
    )


def get_persistence() -> PersistenceUnitOfWork | None:
    return _persistence


def _resolve_encryption_provider() -> EncryptionProvider:
    """Resolve the encryption provider named by CODESONAR_ENCRYPTION_PROVIDER."""
    provider_name = os.environ.get("CODESONAR_ENCRYPTION_PROVIDER", "local").strip()
    # The env-key provider is self-contained: materialize it here so shared
    # deployments can select it with CODESONAR_ENCRYPTION_PROVIDER=env-aes-gcm
    # without any other deployment-owned wiring.
    if (
        provider_name == EnvKeyEncryptionProvider.provider_name
        and _external_encryption_provider is None
    ):
        set_external_encryption_provider(EnvKeyEncryptionProvider.from_env())
    if provider_name == "local":
        if not local_dev_enabled():
            raise RuntimeError("Local encryption provider is forbidden in shared mode")
        return LocalDevelopmentEncryptionProvider.from_env()
    if (
        _external_encryption_provider is not None
        and _external_encryption_provider.production_safe
        and provider_name == _external_encryption_provider.provider_name
    ):
        return _external_encryption_provider
    raise RuntimeError("Configured production encryption provider is unavailable")


# Expected Alembic head revision for the configured database. Bump this every
# time a new migration ships; TestAlembicRevisionPinConsistency fails loudly
# in CI if the pin drifts from the migration scripts, so production startup
# can never desync again. (The pin is hardcoded rather than derived from the
# script directory because the app runs pip-installed on Render, where the
# migration scripts are not next to the installed package.)
REQUIRED_ALEMBIC_REVISION = "20261006_0008"


def _initialize_schema(engine: Engine, config: PersistenceConfig) -> None:
    """Prepare the schema for the configured database."""
    # Local SQLite gets programmatic schema creation for developer convenience.
    # Shared PostgreSQL must be migrated explicitly with Alembic.
    if config.is_sqlite:
        metadata.create_all(engine)
        if engine.url.database and engine.url.database != ":memory:":
            secure_data_file(Path(os.path.abspath(engine.url.database)))
        return
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    # Startup fails closed when the database has not been migrated to the
    # head revision shipped with this build.
    if revision != REQUIRED_ALEMBIC_REVISION:
        raise RuntimeError(
            f"Database schema is at Alembic revision {revision!r}, "
            f"expected {REQUIRED_ALEMBIC_REVISION!r}"
        )


def _wire_runtime_stores(persistence: PersistenceUnitOfWork) -> None:
    """Publish the persistence stores to the application's runtime registries."""
    from app.compliance.records import set_compliance_store
    from app.github_app import (
        set_installation_store,
        set_webhook_audit_store,
        set_webhook_job_store,
    )
    from app.main import set_history_store
    from app.ml.outcomes.runtime import set_outcome_store
    from app.oauth import set_oauth_user_store
    from app.projects import set_project_store

    set_history_store(persistence.history)  # type: ignore[arg-type]
    set_project_store(persistence.projects)  # type: ignore[arg-type]
    set_oauth_user_store(persistence.users)
    set_compliance_store(persistence.compliance)
    set_installation_store(persistence.installations)  # type: ignore[arg-type]
    set_webhook_audit_store(persistence.webhook_audit)  # type: ignore[arg-type]
    set_webhook_job_store(persistence.webhook_jobs)  # type: ignore[arg-type]
    set_outcome_store(persistence.outcomes)  # type: ignore[arg-type]


def _import_legacy_users(persistence: PersistenceUnitOfWork) -> None:
    """One-time migration off the legacy JSON user file."""
    from app.oauth import OAuthUserStore

    # If accounts exist in ~/.code-sonar/oauth-users.json but the users table
    # is empty, import them (preserving ids so existing sessions keep
    # working). The JSON file is left untouched.
    legacy_path = OAuthUserStore().path
    try:
        imported = persistence.users.import_legacy_json(legacy_path)
    except Exception as exc:
        raise RuntimeError(f"Legacy user import failed: {exc}") from exc
    if imported:
        print(f"Imported {imported} user(s) from {legacy_path}", flush=True)


def _wire_validation_service(persistence: PersistenceUnitOfWork) -> None:
    """Rebuild the remediation validation service against the live stores."""
    from app.remediation.runtime import get_validation_service, set_validation_service
    from app.remediation.validation import RemediationValidationService

    previous_validation = get_validation_service()
    set_validation_service(
        RemediationValidationService(
            commands=previous_validation.commands,
            history_store=persistence.history,  # type: ignore[arg-type]
            outcome_store=persistence.outcomes,  # type: ignore[arg-type]
            workspace_root=previous_validation.workspace_root,
            runner=previous_validation.runner,
            scanner=previous_validation.scanner,
        )
    )


def configure_persistence_from_env() -> PersistenceUnitOfWork | None:
    """Wire SQL repositories only when an explicit database URL is configured."""
    global _persistence
    config = persistence_config_from_env()
    validate_persistence_config(config)
    if config.database_url is None:
        if os.environ.get("RENDER"):
            # Render's filesystem is ephemeral: without the database, scan
            # history silently falls back to a JSONL file that is wiped on
            # every redeploy. Scream instead of losing data quietly.
            logger.error(
                "RENDER is set but no database URL is configured — scan "
                "history will use the ephemeral JSONL store and WILL BE LOST "
                "on redeploy. Set CODESONAR_DATABASE_URL."
            )
        _persistence = None
        return None

    encryption = _resolve_encryption_provider()
    engine = create_engine(psycopg3_database_url(config.database_url), pool_pre_ping=True)
    _initialize_schema(engine, config)
    persistence = PersistenceUnitOfWork(engine, encryption)
    _wire_runtime_stores(persistence)
    _import_legacy_users(persistence)
    _wire_validation_service(persistence)
    _persistence = persistence
    return persistence


def record_project_scan_atomically(
    project_id: str,
    record: ScanRecord,
    *,
    history_store: Any,
    project_store: Any,
) -> None:
    persistence = get_persistence()
    if persistence is not None:
        persistence.record_project_scan(project_id, record)
        return
    history_store.append(record)
    project_store.record_scan(project_id, scan_id=record.scan_id, score=record.score)
