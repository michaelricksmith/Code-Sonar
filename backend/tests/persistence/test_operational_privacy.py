"""Operational privacy persistence invariants."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app.history import ScanRecord
from app.main import app
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.privacy import EXPORT_VERSION, RetentionPolicy
from app.persistence.runtime import PersistenceUnitOfWork
from app.persistence.schema import (
    deletion_receipts,
    metadata,
    privacy_audit_events,
    tenants,
)
from app.projects import ProjectRecord
from app.security.tenant import bind_tenant, reset_tenant


class RecordingErasure:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def destroy_tenant_key(self, tenant_id: str) -> str:
        self.calls.append(tenant_id)
        return "destroyed"


@pytest.fixture
def privacy_uow(
    tmp_path: Path,
) -> Generator[tuple[PersistenceUnitOfWork, RecordingErasure], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'privacy.db'}")
    metadata.create_all(engine)
    erasure = RecordingErasure()
    uow = PersistenceUnitOfWork(engine, LocalDevelopmentEncryptionProvider(b"p" * 32), erasure)
    yield uow, erasure
    engine.dispose()


def _project(root: Path, project_id: str = "project-one") -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id,
        provider="github",
        owner="acme",
        name="private-repo",
        default_branch="main",
        connected_at="2026-09-02T00:00:00+00:00",
        local_checkout_path=str(root / "host" / "secret-checkout"),
    )


def _scan(scan_id: str, scanned_at: str) -> ScanRecord:
    return ScanRecord(
        scan_id=scan_id,
        tenant_id="tenant-retention",
        repository_id="repository-one",
        repository_path="repository",
        scanned_at=scanned_at,
        schema_version="1.0",
        scoring_version="1.0",
        score=700,
        grade="B",
        total_debt_points=0,
        finding_count=0,
        category_scores={},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={},
        findings=[],
    )


def test_retention_policy_and_jobs_are_tenant_isolated(
    privacy_uow: tuple[PersistenceUnitOfWork, RecordingErasure],
) -> None:
    uow, _ = privacy_uow
    first = bind_tenant("tenant-a")
    try:
        uow.privacy.set_retention_policy(RetentionPolicy(scan_retention_days=10))
        job = uow.privacy.create_export_job()
    finally:
        reset_tenant(first)
    second = bind_tenant("tenant-b")
    try:
        assert uow.privacy.get_retention_policy().scan_retention_days == 365
        assert uow.privacy.get_export_job(job.job_id) is None
        assert uow.privacy.get_export_archive(job.job_id) is None
    finally:
        reset_tenant(second)


def test_export_is_encrypted_integrity_bound_and_contains_no_host_path_or_tenant_id(
    privacy_uow: tuple[PersistenceUnitOfWork, RecordingErasure], tmp_path: Path
) -> None:
    uow, _ = privacy_uow
    token = bind_tenant("tenant-private")
    try:
        uow.projects.upsert(_project(tmp_path))
        job = uow.privacy.create_export_job()
        archive = uow.privacy.get_export_archive(job.job_id)
        assert archive is not None
        assert job.state == "completed"
        assert job.archive_version == EXPORT_VERSION
        assert job.archive_sha256 == hashlib.sha256(archive.encode()).hexdigest()
        assert "secret-checkout" not in archive
        assert "tenant-private" not in archive
        manifest = uow.privacy.verify_export_archive(job.job_id, archive)
        with pytest.raises(ValueError, match="integrity"):
            uow.privacy.verify_export_archive(job.job_id, archive[:-1] + "A")
    finally:
        reset_tenant(token)
    assert manifest["archive_version"] == EXPORT_VERSION
    assert manifest["counts"]["projects"] == 1
    serialized = str(manifest)
    assert "secret-checkout" not in serialized
    assert "tenant-private" not in serialized
    assert "checkout_path_ciphertext" not in serialized


def test_deletion_recovery_eligibility_idempotency_and_content_free_receipt(
    privacy_uow: tuple[PersistenceUnitOfWork, RecordingErasure], tmp_path: Path
) -> None:
    uow, erasure = privacy_uow
    token = bind_tenant("tenant-delete")
    try:
        uow.projects.upsert(_project(tmp_path))
        uow.privacy.set_retention_policy(RetentionPolicy(deletion_recovery_days=2))
        first_state = uow.privacy.request_deletion()
        assert uow.privacy.request_deletion() == first_state
        with pytest.raises(ValueError, match="recovery window"):
            uow.privacy.hard_delete(request_token="ticket-123")
        eligible = datetime.fromisoformat(first_state.hard_delete_eligible_at or "")
        receipt = uow.privacy.hard_delete(
            request_token="ticket-123", now=eligible + timedelta(seconds=1)
        )
        repeated = uow.privacy.hard_delete(
            request_token="ticket-123", now=eligible + timedelta(days=1)
        )
    finally:
        reset_tenant(token)
    assert repeated == receipt
    assert erasure.calls == ["tenant-delete"]
    assert "tenant-delete" not in str(receipt)
    with uow.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(tenants)).scalar_one() == 0
        raw = connection.execute(select(deletion_receipts)).mappings().one()
    assert set(raw) == {
        "receipt_id",
        "request_fingerprint",
        "completed_at",
        "schema_version",
        "crypto_erasure_status",
    }
    assert "tenant-delete" not in str(dict(raw))


def test_retention_rejects_invalid_windows(
    privacy_uow: tuple[PersistenceUnitOfWork, RecordingErasure],
) -> None:
    uow, _ = privacy_uow
    token = bind_tenant("tenant-a")
    try:
        with pytest.raises(ValueError):
            uow.privacy.set_retention_policy(RetentionPolicy(scan_retention_days=-1))
        with pytest.raises(ValueError):
            uow.privacy.set_retention_policy(RetentionPolicy(deletion_recovery_days=31))
    finally:
        reset_tenant(token)


def test_retention_eligibility_is_tenant_scoped_and_non_destructive(
    privacy_uow: tuple[PersistenceUnitOfWork, RecordingErasure],
) -> None:
    uow, _ = privacy_uow
    token = bind_tenant("tenant-retention")
    try:
        uow.privacy.set_retention_policy(
            RetentionPolicy(scan_retention_days=30, export_retention_days=0)
        )
        uow.history.append(_scan("expired", "2026-01-01T00:00:00+00:00"))
        uow.history.append(_scan("current", "2026-09-01T00:00:00+00:00"))
        export = uow.privacy.create_export_job()
        at = datetime(2026, 9, 2, tzinfo=timezone.utc)
        assert uow.privacy.eligible_scan_ids(now=at) == ["expired"]
        assert export.expires_at is not None
        after_expiry = datetime.fromisoformat(export.expires_at) + timedelta(seconds=1)
        assert uow.privacy.eligible_export_job_ids(now=after_expiry) == [export.job_id]
        assert uow.history.get("expired") is not None
        assert uow.privacy.get_export_archive(export.job_id) is not None
    finally:
        reset_tenant(token)


def test_privacy_api_requires_auth_and_audits_export(
    privacy_uow: tuple[PersistenceUnitOfWork, RecordingErasure],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow, _ = privacy_uow
    from app.persistence import runtime

    monkeypatch.setattr(runtime, "_persistence", uow)
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    monkeypatch.setenv(
        "CODESONAR_API_TENANT_TOKENS",
        '{"tenant-a":"token-a","tenant-b":"token-b"}',
    )
    client = TestClient(app)
    assert client.post("/api/privacy/exports").status_code == 401
    response = client.post("/api/privacy/exports", headers={"Authorization": "Bearer token-a"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    denied = client.get(
        f"/api/privacy/exports/{job_id}",
        headers={"Authorization": "Bearer token-b"},
    )
    assert denied.status_code == 404
    token = bind_tenant("tenant-a")
    try:
        with uow.engine.connect() as connection:
            actions = (
                connection.execute(
                    select(privacy_audit_events.c.action)
                    .where(privacy_audit_events.c.tenant_id == "tenant-a")
                    .order_by(privacy_audit_events.c.occurred_at)
                )
                .scalars()
                .all()
            )
    finally:
        reset_tenant(token)
    assert actions == ["export.requested", "export.completed"]
