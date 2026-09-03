"""Runtime wiring for the transactional persistence unit of work."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text, update

from app.history import ScanRecord
from app.persistence.config import (
    persistence_config_from_env,
    secure_data_file,
    validate_persistence_config,
)
from app.persistence.crypto import EncryptionProvider, LocalDevelopmentEncryptionProvider
from app.persistence.privacy import CryptoErasureHook, SqlPrivacyRepository
from app.persistence.repositories import (
    SqlGitHubInstallationStore,
    SqlHistoryStore,
    SqlOutcomeStore,
    SqlProjectStore,
    SqlWebhookAuditStore,
    SqlWebhookScanJobStore,
)
from app.persistence.schema import metadata, projects
from app.security.runtime import local_dev_enabled
from app.security.tenant import current_tenant_id


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
        self.privacy = SqlPrivacyRepository(self.engine, self.encryption, self.crypto_erasure)

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


def configure_persistence_from_env() -> PersistenceUnitOfWork | None:
    """Wire SQL repositories only when an explicit database URL is configured."""
    global _persistence
    config = persistence_config_from_env()
    validate_persistence_config(config)
    if config.database_url is None:
        _persistence = None
        return None

    provider_name = os.environ.get("CODESONAR_ENCRYPTION_PROVIDER", "local").strip()
    if provider_name == "local":
        if not local_dev_enabled():
            raise RuntimeError("Local encryption provider is forbidden in shared mode")
        encryption: EncryptionProvider = LocalDevelopmentEncryptionProvider.from_env()
    elif (
        _external_encryption_provider is not None
        and _external_encryption_provider.production_safe
        and provider_name == _external_encryption_provider.provider_name
    ):
        encryption = _external_encryption_provider
    else:
        raise RuntimeError("Configured production encryption provider is unavailable")

    engine = create_engine(config.database_url, pool_pre_ping=True)
    # Local SQLite gets programmatic schema creation for developer convenience.
    # Shared PostgreSQL must be migrated explicitly with Alembic.
    if config.is_sqlite:
        metadata.create_all(engine)
        if engine.url.database and engine.url.database != ":memory:":
            secure_data_file(Path(os.path.abspath(engine.url.database)))
    else:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        if revision != "20260902_0002":
            raise RuntimeError("Database schema is not at required Alembic revision")
    persistence = PersistenceUnitOfWork(engine, encryption)

    from app.github_app import (
        set_installation_store,
        set_webhook_audit_store,
        set_webhook_job_store,
    )
    from app.main import set_history_store
    from app.ml.outcomes.runtime import set_outcome_store
    from app.projects import set_project_store
    from app.remediation.runtime import get_validation_service, set_validation_service
    from app.remediation.validation import RemediationValidationService

    set_history_store(persistence.history)  # type: ignore[arg-type]
    set_project_store(persistence.projects)  # type: ignore[arg-type]
    set_installation_store(persistence.installations)  # type: ignore[arg-type]
    set_webhook_audit_store(persistence.webhook_audit)  # type: ignore[arg-type]
    set_webhook_job_store(persistence.webhook_jobs)  # type: ignore[arg-type]
    set_outcome_store(persistence.outcomes)  # type: ignore[arg-type]
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
