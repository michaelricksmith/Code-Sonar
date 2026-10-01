"""Unit tests for ``app.persistence.privacy`` (gap coverage).

``tests/persistence/test_operational_privacy.py`` covers the big operational
invariants: tenant isolation, export encryption/integrity, deletion recovery
and idempotency, invalid retention windows, tenant-scoped eligibility, and
the HTTP API surface. ``tests/persistence/test_postgres_integration.py``
covers the Postgres-only advisory-lock path.

This module covers the remaining public surface that those files do not
exercise:

- ``RetentionPolicy`` defaults, boundary validation (``30`` ok / ``31``
  rejected), and rejection of non-integer values.
- Module constants (``EXPORT_VERSION`` / ``RECEIPT_VERSION``), ``_now`` /
  ``_iso`` helpers, and the ``export_aad`` binding format.
- ``_safe_json`` sanitization: blocked keys, case-insensitivity, and
  recursion through nested dicts and lists.
- ``UnsupportedCryptoErasureHook`` and the default erasure fallback in
  ``SqlPrivacyRepository`` (receipt carries ``not_configured``).
- ``ExportJob`` / ``DeletionState`` / ``DeletionReceipt`` shapes and
  frozen-ness.
- Retention policy update path (second ``set`` overwrites) and defaults for
  unknown tenants.
- Deletion state default, upgrade of an existing ``active`` lifecycle row,
  zero-day recovery eligibility, ``hard_delete`` without a pending request,
  and per-token request fingerprints.
- Export failure path: a broken encryption provider marks the job
  ``failed`` with ``export_failed`` and the original error propagates.
- ``get_export_job`` / ``get_export_archive`` misses, ``verify_export_archive``
  on an unknown job, unexpired-job exclusion from eligibility, and
  ``eligible_scan_ids`` ordering.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, insert, select

from app.history import ScanRecord
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.privacy import (
    EXPORT_VERSION,
    RECEIPT_VERSION,
    DeletionReceipt,
    DeletionState,
    ExportJob,
    RetentionPolicy,
    UnsupportedCryptoErasureHook,
    _iso,
    _now,
    _safe_json,
    export_aad,
)
from app.persistence.runtime import PersistenceUnitOfWork
from app.persistence.schema import deletion_receipts, metadata, privacy_jobs, tenant_lifecycle
from app.security.tenant import bind_tenant, reset_tenant


@pytest.fixture
def privacy_uow(
    tmp_path: Path,
) -> Generator[PersistenceUnitOfWork, None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'privacy.db'}")
    metadata.create_all(engine)
    # No crypto-erasure hook on purpose: exercises the honest fallback.
    uow = PersistenceUnitOfWork(engine, LocalDevelopmentEncryptionProvider(b"p" * 32))
    yield uow
    engine.dispose()


def _scan(scan_id: str, scanned_at: str, tenant_id: str) -> ScanRecord:
    return ScanRecord(
        scan_id=scan_id,
        tenant_id=tenant_id,
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


class _FailingEncryption:
    def encrypt(self, plaintext: str, *, aad: bytes) -> str:
        raise RuntimeError("boom")

    def decrypt(self, ciphertext: str, *, aad: bytes) -> str:
        raise RuntimeError("boom")


class TestRetentionPolicyValidation:
    def test_defaults(self):
        policy = RetentionPolicy()
        assert policy.scan_retention_days == 365
        assert policy.audit_retention_days == 365
        assert policy.export_retention_days == 7
        assert policy.backup_retention_days == 30
        assert policy.deletion_recovery_days == 7
        assert policy.backup_deletion_lag_days == 30

    def test_boundary_recovery_days_accepted(self):
        policy = RetentionPolicy(deletion_recovery_days=30)
        policy.validate()
        assert asdict(policy)["deletion_recovery_days"] == 30

    def test_zero_windows_accepted(self):
        RetentionPolicy(
            scan_retention_days=0,
            audit_retention_days=0,
            export_retention_days=0,
            backup_retention_days=0,
            deletion_recovery_days=0,
            backup_deletion_lag_days=0,
        ).validate()

    def test_rejects_float_values(self):
        with pytest.raises(ValueError, match="non-negative"):
            RetentionPolicy(scan_retention_days=1.5).validate()

    def test_rejects_negative_and_overlong_recovery(self):
        with pytest.raises(ValueError, match="non-negative"):
            RetentionPolicy(export_retention_days=-1).validate()
        with pytest.raises(ValueError, match="30 days"):
            RetentionPolicy(deletion_recovery_days=31).validate()


class TestModuleHelpers:
    def test_version_constants(self):
        assert EXPORT_VERSION == "code-sonar-export-v1"
        assert RECEIPT_VERSION == "code-sonar-deletion-receipt-v1"

    def test_export_aad_format(self):
        aad = export_aad("tenant-x", "job-1")
        assert isinstance(aad, bytes)
        assert aad == b"code-sonar:v1:tenant-x:privacy_exports:job-1:archive"

    def test_now_is_aware_and_iso_roundtrips(self):
        now = _now()
        assert now.tzinfo is not None
        assert datetime.fromisoformat(_iso(now)) == now


class TestSafeJson:
    def test_strips_blocked_keys_case_insensitively(self):
        cleaned = _safe_json({
            "Authorization": "bearer x",
            "TOKEN": "y",
            "Secret": "z",
            "private_key": "k",
            "keep": "ok",
        })
        assert cleaned == {"keep": "ok"}

    def test_recurses_through_nested_structures(self):
        cleaned = _safe_json({
            "outer": {
                "repository_path": "/home/secret",
                "inner": [{"checkout_path_ciphertext": "abc", "n": 1}],
            },
            "tenant_id": "t-1",
            "rows": 3,
        })
        assert cleaned == {"outer": {"inner": [{"n": 1}]}, "rows": 3}

    def test_passes_through_scalars(self):
        assert _safe_json("text") == "text"
        assert _safe_json(None) is None
        assert _safe_json(42) == 42
        assert _safe_json([]) == []


class TestErasureHook:
    def test_unsupported_hook_is_honest(self):
        assert UnsupportedCryptoErasureHook().destroy_tenant_key("any-tenant") == "not_configured"


class TestDataclassShapes:
    def test_export_job_fields(self):
        job = ExportJob(
            job_id="export_1",
            state="completed",
            requested_at="2026-09-28T00:00:00+00:00",
            completed_at="2026-09-28T00:00:01+00:00",
            archive_sha256="deadbeef",
            archive_version=EXPORT_VERSION,
            expires_at=None,
        )
        assert job.job_id == "export_1"
        assert job.state == "completed"
        assert job.archive_version == EXPORT_VERSION
        assert job.expires_at is None

    def test_deletion_state_and_receipt_fields(self):
        state = DeletionState("active", None, None)
        receipt = DeletionReceipt(
            "del_1", "2026-09-28T00:00:00+00:00", RECEIPT_VERSION, "destroyed"
        )
        assert state.state == "active"
        assert state.delete_requested_at is None
        assert receipt.receipt_id == "del_1"
        assert receipt.crypto_erasure_status == "destroyed"

    def test_dataclasses_are_frozen(self):
        with pytest.raises(FrozenInstanceError):
            RetentionPolicy().scan_retention_days = 1  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            DeletionState("active", None, None).state = "x"  # type: ignore[misc]


class TestRetentionPolicyPersistence:
    def test_second_set_updates_existing_row(self, privacy_uow: PersistenceUnitOfWork) -> None:
        token = bind_tenant("t-policy")
        try:
            returned = privacy_uow.privacy.set_retention_policy(
                RetentionPolicy(scan_retention_days=10)
            )
            assert returned == RetentionPolicy(scan_retention_days=10)
            second = privacy_uow.privacy.set_retention_policy(
                RetentionPolicy(scan_retention_days=20, audit_retention_days=5)
            )
            assert second.scan_retention_days == 20
            stored = privacy_uow.privacy.get_retention_policy()
            assert stored.scan_retention_days == 20
            assert stored.audit_retention_days == 5
            assert stored.backup_retention_days == 30
        finally:
            reset_tenant(token)

    def test_unknown_tenant_gets_defaults(self, privacy_uow: PersistenceUnitOfWork) -> None:
        token = bind_tenant("t-fresh")
        try:
            assert privacy_uow.privacy.get_retention_policy() == RetentionPolicy()
        finally:
            reset_tenant(token)


class TestDeletionLifecycle:
    def test_get_deletion_state_defaults_to_active(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        token = bind_tenant("t-state")
        try:
            assert privacy_uow.privacy.get_deletion_state() == DeletionState("active", None, None)
        finally:
            reset_tenant(token)

    def test_request_deletion_upgrades_existing_active_row(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        with privacy_uow.engine.begin() as connection:
            connection.execute(
                insert(tenant_lifecycle).values(
                    tenant_id="t-upgrade",
                    state="active",
                    delete_requested_at=None,
                    hard_delete_eligible_at=None,
                    updated_at="2026-01-01T00:00:00+00:00",
                )
            )
        token = bind_tenant("t-upgrade")
        try:
            state = privacy_uow.privacy.request_deletion()
            assert state.state == "pending_deletion"
            assert state.delete_requested_at is not None
        finally:
            reset_tenant(token)

    def test_zero_day_recovery_is_immediately_eligible(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        token = bind_tenant("t-zero")
        try:
            privacy_uow.privacy.set_retention_policy(RetentionPolicy(deletion_recovery_days=0))
            state = privacy_uow.privacy.request_deletion()
            assert state.state == "pending_deletion"
            assert state.hard_delete_eligible_at == state.delete_requested_at
        finally:
            reset_tenant(token)

    def test_hard_delete_requires_pending_request(self, privacy_uow: PersistenceUnitOfWork) -> None:
        token = bind_tenant("t-none")
        try:
            with pytest.raises(ValueError, match="no pending deletion"):
                privacy_uow.privacy.hard_delete(request_token="ticket-1")
        finally:
            reset_tenant(token)

    def test_hard_delete_uses_unsupported_erasure_hook_by_default(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        assert isinstance(privacy_uow.privacy.crypto_erasure, UnsupportedCryptoErasureHook)
        token = bind_tenant("t-fallback")
        try:
            privacy_uow.privacy.set_retention_policy(RetentionPolicy(deletion_recovery_days=0))
            privacy_uow.privacy.request_deletion()
            receipt = privacy_uow.privacy.hard_delete(request_token="ticket-1")
        finally:
            reset_tenant(token)
        assert receipt.crypto_erasure_status == "not_configured"
        assert receipt.schema_version == RECEIPT_VERSION
        assert receipt.receipt_id.startswith("del_")

    def test_request_token_fingerprints_are_distinct(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        receipts = []
        for tenant_id, token_value in (("t-fp-1", "token-a"), ("t-fp-2", "token-b")):
            token = bind_tenant(tenant_id)
            try:
                privacy_uow.privacy.set_retention_policy(RetentionPolicy(deletion_recovery_days=0))
                privacy_uow.privacy.request_deletion()
                receipts.append(privacy_uow.privacy.hard_delete(request_token=token_value))
            finally:
                reset_tenant(token)
        assert receipts[0].receipt_id != receipts[1].receipt_id
        with privacy_uow.engine.connect() as connection:
            fingerprints = connection.execute(
                select(deletion_receipts.c.request_fingerprint)
            ).scalars().all()
        assert len(fingerprints) == 2
        assert fingerprints[0] != fingerprints[1]


class TestExportJobLifecycle:
    def test_get_export_job_missing_returns_none(self, privacy_uow: PersistenceUnitOfWork) -> None:
        token = bind_tenant("t-export")
        try:
            assert privacy_uow.privacy.get_export_job("export_missing") is None
        finally:
            reset_tenant(token)

    def test_get_export_archive_missing_returns_none(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        token = bind_tenant("t-export")
        try:
            assert privacy_uow.privacy.get_export_archive("export_missing") is None
        finally:
            reset_tenant(token)

    def test_verify_export_unknown_job_raises_lookup(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        token = bind_tenant("t-export")
        try:
            with pytest.raises(LookupError, match="not found"):
                privacy_uow.privacy.verify_export_archive("export_missing", "archive")
        finally:
            reset_tenant(token)

    def test_export_failure_marks_job_failed_and_reraises(self, tmp_path: Path) -> None:
        engine = create_engine(f"sqlite:///{tmp_path / 'privacy-fail.db'}")
        metadata.create_all(engine)
        uow = PersistenceUnitOfWork(engine, _FailingEncryption())
        token = bind_tenant("t-fail")
        try:
            with pytest.raises(RuntimeError, match="boom"):
                uow.privacy.create_export_job()
            with uow.engine.connect() as connection:
                row = connection.execute(
                    select(privacy_jobs).where(privacy_jobs.c.tenant_id == "t-fail")
                ).mappings().one()
            assert row["state"] == "failed"
            assert row["error_code"] == "export_failed"
            assert uow.privacy.get_export_job(row["job_id"]) is not None
        finally:
            reset_tenant(token)
            engine.dispose()

    def test_failed_export_has_no_archive(self, tmp_path: Path) -> None:
        engine = create_engine(f"sqlite:///{tmp_path / 'privacy-fail2.db'}")
        metadata.create_all(engine)
        uow = PersistenceUnitOfWork(engine, _FailingEncryption())
        token = bind_tenant("t-fail2")
        try:
            with pytest.raises(RuntimeError, match="boom"):
                uow.privacy.create_export_job()
            with uow.engine.connect() as connection:
                job_id = connection.execute(
                    select(privacy_jobs.c.job_id).where(privacy_jobs.c.tenant_id == "t-fail2")
                ).scalar_one()
            assert uow.privacy.get_export_archive(job_id) is None
        finally:
            reset_tenant(token)
            engine.dispose()

    def test_unexpired_export_is_not_eligible(self, privacy_uow: PersistenceUnitOfWork) -> None:
        token = bind_tenant("t-elig")
        try:
            job = privacy_uow.privacy.create_export_job()
            assert job.state == "completed"
            assert privacy_uow.privacy.eligible_export_job_ids() == []
        finally:
            reset_tenant(token)

    def test_eligible_scan_ids_order_by_scanned_at_then_id(
        self, privacy_uow: PersistenceUnitOfWork
    ) -> None:
        token = bind_tenant("t-order")
        try:
            privacy_uow.privacy.set_retention_policy(RetentionPolicy(scan_retention_days=30))
            privacy_uow.history.append(_scan("b", "2026-01-02T00:00:00+00:00", "t-order"))
            privacy_uow.history.append(_scan("a", "2026-01-01T00:00:00+00:00", "t-order"))
            privacy_uow.history.append(_scan("a2", "2026-01-01T00:00:00+00:00", "t-order"))
            at = datetime(2026, 9, 2, tzinfo=timezone.utc)
            assert privacy_uow.privacy.eligible_scan_ids(now=at) == ["a", "a2", "b"]
        finally:
            reset_tenant(token)

    def test_expired_export_becomes_eligible(self, privacy_uow: PersistenceUnitOfWork) -> None:
        token = bind_tenant("t-expire")
        try:
            privacy_uow.privacy.set_retention_policy(RetentionPolicy(export_retention_days=0))
            job = privacy_uow.privacy.create_export_job()
            assert job.expires_at is not None
            after = datetime.fromisoformat(job.expires_at) + timedelta(seconds=1)
            assert privacy_uow.privacy.eligible_export_job_ids(now=after) == [job.job_id]
        finally:
            reset_tenant(token)
