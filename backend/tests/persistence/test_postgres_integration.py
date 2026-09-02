"""PostgreSQL-only concurrency smoke; skipped without the CI service URL."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine

from app.github_app import WebhookAuditRecord
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.runtime import PersistenceUnitOfWork
from app.persistence.schema import metadata
from app.projects import ProjectRecord
from app.security.tenant import bind_tenant, reset_tenant


@pytest.mark.skipif(
    not os.environ.get("CODESONAR_TEST_POSTGRES_URL"),
    reason="PostgreSQL integration service is not configured",
)
def test_postgres_atomic_webhook_replay_claim() -> None:
    engine = create_engine(os.environ["CODESONAR_TEST_POSTGRES_URL"])
    metadata.drop_all(engine)
    metadata.create_all(engine)
    persistence = PersistenceUnitOfWork(engine, LocalDevelopmentEncryptionProvider(b"k" * 32))
    token = bind_tenant("postgres-test")
    try:
        record = WebhookAuditRecord(
            delivery_id="delivery-" + uuid.uuid4().hex,
            event="push",
            action=None,
            repository_full_name="acme/repo",
            installation_id=1,
            project_id=None,
            accepted=True,
            scan_triggered=False,
            received_at="now",
        )
        assert persistence.webhook_audit.claim(record) is True
        assert persistence.webhook_audit.claim(record) is False
        persistence.projects.upsert(
            ProjectRecord(
                project_id="project-postgres",
                provider="github",
                owner="acme",
                name="repo",
                default_branch="main",
                connected_at="now",
                local_checkout_path="/private/checkout",
            )
        )
        job = persistence.webhook_jobs.enqueue(
            delivery_id=record.delivery_id,
            project_id="project-postgres",
            installation_id=1,
        )
        assert persistence.webhook_jobs.claim_queued(job.job_id, worker_id="worker-a") is True
        assert persistence.webhook_jobs.claim_queued(job.job_id, worker_id="worker-b") is False
    finally:
        reset_tenant(token)
        metadata.drop_all(engine)
