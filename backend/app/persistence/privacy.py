"""Tenant-scoped retention, export, and deletion operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, cast

from sqlalchemy import Engine, and_, delete, insert, select, text, update

from app.persistence.crypto import EncryptionProvider
from app.persistence.repositories import _tenant
from app.persistence.schema import (
    deletion_receipts,
    findings,
    github_installations,
    migration_ledger,
    privacy_audit_events,
    privacy_jobs,
    projects,
    remediation_outcomes,
    scans,
    tenant_lifecycle,
    tenant_retention_policies,
    tenants,
    webhook_deliveries,
    webhook_jobs,
)
from app.security.tenant import current_tenant_id

EXPORT_VERSION = "code-sonar-export-v1"
RECEIPT_VERSION = "code-sonar-deletion-receipt-v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True)
class RetentionPolicy:
    scan_retention_days: int = 365
    audit_retention_days: int = 365
    export_retention_days: int = 7
    backup_retention_days: int = 30
    deletion_recovery_days: int = 7
    backup_deletion_lag_days: int = 30

    def validate(self) -> None:
        values = asdict(self)
        if any(not isinstance(value, int) or value < 0 for value in values.values()):
            raise ValueError("Retention periods must be non-negative whole days")
        if self.deletion_recovery_days > 30:
            raise ValueError("Deletion recovery may not exceed 30 days")


@dataclass(frozen=True)
class ExportJob:
    job_id: str
    state: str
    requested_at: str
    completed_at: str | None
    archive_sha256: str | None
    archive_version: str | None
    expires_at: str | None


@dataclass(frozen=True)
class DeletionState:
    state: str
    delete_requested_at: str | None
    hard_delete_eligible_at: str | None


@dataclass(frozen=True)
class DeletionReceipt:
    receipt_id: str
    completed_at: str
    schema_version: str
    crypto_erasure_status: str


class CryptoErasureHook(Protocol):
    """Deployment hook for destruction of a tenant's envelope/data key."""

    def destroy_tenant_key(self, tenant_id: str) -> str: ...


class UnsupportedCryptoErasureHook:
    """Honest local fallback: records that no independent tenant key existed."""

    def destroy_tenant_key(self, tenant_id: str) -> str:
        del tenant_id
        return "not_configured"


def export_aad(tenant_id: str, job_id: str) -> bytes:
    return f"code-sonar:v1:{tenant_id}:privacy_exports:{job_id}:archive".encode()


def _safe_json(value: Any) -> Any:
    """Strip host paths, credentials, ciphertext, and tenant bindings recursively."""
    blocked = {
        "tenant_id",
        "repository_path",
        "repo_path",
        "local_checkout_path",
        "checkout_path_ciphertext",
        "authorization",
        "token",
        "secret",
        "credential",
        "private_key",
        "archive_ciphertext",
    }
    if isinstance(value, dict):
        return {key: _safe_json(item) for key, item in value.items() if key.lower() not in blocked}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    return value


class SqlPrivacyRepository:
    def __init__(
        self,
        engine: Engine,
        encryption: EncryptionProvider,
        crypto_erasure: CryptoErasureHook | None = None,
    ) -> None:
        self.engine = engine
        self.encryption = encryption
        self.crypto_erasure = crypto_erasure or UnsupportedCryptoErasureHook()

    def set_retention_policy(self, policy: RetentionPolicy) -> RetentionPolicy:
        policy.validate()
        tenant_id = current_tenant_id()
        values = {**asdict(policy), "tenant_id": tenant_id, "updated_at": _iso(_now())}
        with self.engine.begin() as connection:
            _tenant(connection, tenant_id)
            existing = connection.execute(
                select(tenant_retention_policies.c.tenant_id).where(
                    tenant_retention_policies.c.tenant_id == tenant_id
                )
            ).first()
            if existing:
                connection.execute(
                    update(tenant_retention_policies)
                    .where(tenant_retention_policies.c.tenant_id == tenant_id)
                    .values(**values)
                )
            else:
                connection.execute(insert(tenant_retention_policies).values(**values))
            self._audit(connection, tenant_id, "retention.updated", None, True)
        return policy

    def get_retention_policy(self) -> RetentionPolicy:
        tenant_id = current_tenant_id()
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(tenant_retention_policies).where(
                        tenant_retention_policies.c.tenant_id == tenant_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return RetentionPolicy()
        return RetentionPolicy(**{key: row[key] for key in asdict(RetentionPolicy())})

    def eligible_scan_ids(self, *, now: datetime | None = None) -> list[str]:
        """Return tenant-owned scan IDs eligible for a future retention worker."""
        cutoff = (now or _now()) - timedelta(days=self.get_retention_policy().scan_retention_days)
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(scans.c.scan_id)
                    .where(
                        and_(
                            scans.c.tenant_id == current_tenant_id(),
                            scans.c.scanned_at < _iso(cutoff),
                        )
                    )
                    .order_by(scans.c.scanned_at, scans.c.scan_id)
                ).scalars()
            )

    def eligible_export_job_ids(self, *, now: datetime | None = None) -> list[str]:
        """Return expired tenant export IDs without deleting their artifacts."""
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(privacy_jobs.c.job_id)
                    .where(
                        and_(
                            privacy_jobs.c.tenant_id == current_tenant_id(),
                            privacy_jobs.c.expires_at.is_not(None),
                            privacy_jobs.c.expires_at <= _iso(now or _now()),
                        )
                    )
                    .order_by(privacy_jobs.c.expires_at, privacy_jobs.c.job_id)
                ).scalars()
            )

    def create_export_job(self) -> ExportJob:
        """Create a queued job and run the bounded MVP executor behind that contract."""
        tenant_id = current_tenant_id()
        job_id = "export_" + uuid.uuid4().hex
        requested = _now()
        policy = self.get_retention_policy()
        with self.engine.begin() as connection:
            _tenant(connection, tenant_id)
            connection.execute(
                insert(privacy_jobs).values(
                    tenant_id=tenant_id,
                    job_id=job_id,
                    kind="tenant_export",
                    state="queued",
                    requested_at=_iso(requested),
                )
            )
            self._audit(connection, tenant_id, "export.requested", job_id, True)
        try:
            self._execute_export(job_id, requested, policy)
        except Exception:
            with self.engine.begin() as connection:
                connection.execute(
                    update(privacy_jobs)
                    .where(
                        and_(privacy_jobs.c.tenant_id == tenant_id, privacy_jobs.c.job_id == job_id)
                    )
                    .values(state="failed", error_code="export_failed")
                )
                self._audit(connection, tenant_id, "export.completed", job_id, False)
            raise
        job = self.get_export_job(job_id)
        if job is None:
            raise RuntimeError("Export job disappeared")
        return job

    def _execute_export(self, job_id: str, requested: datetime, policy: RetentionPolicy) -> None:
        tenant_id = current_tenant_id()
        with self.engine.begin() as connection:
            claimed = connection.execute(
                update(privacy_jobs)
                .where(
                    and_(
                        privacy_jobs.c.tenant_id == tenant_id,
                        privacy_jobs.c.job_id == job_id,
                        privacy_jobs.c.state == "queued",
                    )
                )
                .values(state="running")
            )
            if claimed.rowcount != 1:
                raise RuntimeError("Export job is not queued")
            collections: dict[str, list[dict[str, Any]]] = {}
            for name, table in (
                ("projects", projects),
                ("scans", scans),
                ("findings", findings),
                ("github_installations", github_installations),
                ("remediation_outcomes", remediation_outcomes),
                ("retention_policy", tenant_retention_policies),
                ("privacy_audit_events", privacy_audit_events),
            ):
                rows = (
                    connection.execute(select(table).where(table.c.tenant_id == tenant_id))
                    .mappings()
                    .all()
                )
                collections[name] = [_safe_json(dict(row)) for row in rows]
            delivery_rows = connection.execute(
                select(webhook_deliveries.c.delivery_id).where(
                    webhook_deliveries.c.tenant_id == tenant_id
                )
            ).mappings().all()
            collections["webhook_deliveries"] = [dict(row) for row in delivery_rows]
            job_rows = connection.execute(
                select(
                    webhook_jobs.c.job_id,
                    webhook_jobs.c.delivery_id,
                    webhook_jobs.c.project_id,
                    webhook_jobs.c.state,
                ).where(webhook_jobs.c.tenant_id == tenant_id)
            ).mappings().all()
            collections["webhook_jobs"] = [dict(row) for row in job_rows]
            manifest = {
                "archive_version": EXPORT_VERSION,
                "generated_at": _iso(requested),
                "collections": collections,
                "counts": {name: len(rows) for name, rows in collections.items()},
            }
            plaintext = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            archive = self.encryption.encrypt(plaintext, aad=export_aad(tenant_id, job_id))
            digest = hashlib.sha256(archive.encode()).hexdigest()
            completed = _now()
            connection.execute(
                update(privacy_jobs)
                .where(and_(privacy_jobs.c.tenant_id == tenant_id, privacy_jobs.c.job_id == job_id))
                .values(
                    state="completed",
                    completed_at=_iso(completed),
                    archive_ciphertext=archive,
                    archive_sha256=digest,
                    archive_version=EXPORT_VERSION,
                    expires_at=_iso(completed + timedelta(days=policy.export_retention_days)),
                )
            )
            self._audit(connection, tenant_id, "export.completed", job_id, True)

    def get_export_job(self, job_id: str) -> ExportJob | None:
        tenant_id = current_tenant_id()
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(privacy_jobs).where(
                        and_(privacy_jobs.c.tenant_id == tenant_id, privacy_jobs.c.job_id == job_id)
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return ExportJob(**{key: row[key] for key in ExportJob.__dataclass_fields__})

    def get_export_archive(self, job_id: str) -> str | None:
        tenant_id = current_tenant_id()
        with self.engine.connect() as connection:
            return connection.execute(
                select(privacy_jobs.c.archive_ciphertext).where(
                    and_(
                        privacy_jobs.c.tenant_id == tenant_id,
                        privacy_jobs.c.job_id == job_id,
                        privacy_jobs.c.state == "completed",
                    )
                )
            ).scalar_one_or_none()

    def decrypt_export_for_verification(self, job_id: str, archive: str) -> dict[str, Any]:
        raw = self.encryption.decrypt(archive, aad=export_aad(current_tenant_id(), job_id))
        return cast(dict[str, Any], json.loads(raw))

    def verify_export_archive(self, job_id: str, archive: str) -> dict[str, Any]:
        job = self.get_export_job(job_id)
        if job is None or job.archive_sha256 is None:
            raise LookupError("Completed export job not found")
        if not hmac.compare_digest(
            hashlib.sha256(archive.encode()).hexdigest(), job.archive_sha256
        ):
            raise ValueError("Export archive integrity check failed")
        return self.decrypt_export_for_verification(job_id, archive)

    def request_deletion(self) -> DeletionState:
        tenant_id = current_tenant_id()
        policy = self.get_retention_policy()
        requested = _now()
        eligible = requested + timedelta(days=policy.deletion_recovery_days)
        with self.engine.begin() as connection:
            _tenant(connection, tenant_id)
            row = (
                connection.execute(
                    select(tenant_lifecycle).where(tenant_lifecycle.c.tenant_id == tenant_id)
                )
                .mappings()
                .first()
            )
            if row and row["state"] == "pending_deletion":
                return DeletionState(
                    row["state"], row["delete_requested_at"], row["hard_delete_eligible_at"]
                )
            values = {
                "tenant_id": tenant_id,
                "state": "pending_deletion",
                "delete_requested_at": _iso(requested),
                "hard_delete_eligible_at": _iso(eligible),
                "updated_at": _iso(requested),
            }
            if row:
                connection.execute(
                    update(tenant_lifecycle)
                    .where(tenant_lifecycle.c.tenant_id == tenant_id)
                    .values(**values)
                )
            else:
                connection.execute(insert(tenant_lifecycle).values(**values))
            self._audit(connection, tenant_id, "deletion.requested", None, True)
        return DeletionState("pending_deletion", _iso(requested), _iso(eligible))

    def get_deletion_state(self) -> DeletionState:
        tenant_id = current_tenant_id()
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(tenant_lifecycle).where(tenant_lifecycle.c.tenant_id == tenant_id)
                )
                .mappings()
                .first()
            )
        if row is None:
            return DeletionState("active", None, None)
        return DeletionState(
            row["state"], row["delete_requested_at"], row["hard_delete_eligible_at"]
        )

    def hard_delete(self, *, request_token: str, now: datetime | None = None) -> DeletionReceipt:
        """Explicit operator action; never called automatically or by the HTTP API."""
        tenant_id = current_tenant_id()
        fingerprint = hashlib.sha256(f"{tenant_id}:{request_token}".encode()).hexdigest()
        effective_now = now or _now()
        with self.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                lock_key = int(fingerprint[:16], 16) & 0x7FFF_FFFF_FFFF_FFFF
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
                )
            existing = (
                connection.execute(
                    select(deletion_receipts).where(
                        deletion_receipts.c.request_fingerprint == fingerprint
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                return DeletionReceipt(
                    existing["receipt_id"],
                    existing["completed_at"],
                    existing["schema_version"],
                    existing["crypto_erasure_status"],
                )
            state = (
                connection.execute(
                    select(tenant_lifecycle)
                    .where(tenant_lifecycle.c.tenant_id == tenant_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if (
                not state
                or state["state"] != "pending_deletion"
                or not state["hard_delete_eligible_at"]
            ):
                raise ValueError("Tenant has no pending deletion request")
            if effective_now < datetime.fromisoformat(state["hard_delete_eligible_at"]):
                raise ValueError("Tenant is still in the deletion recovery window")
            erasure_status = self.crypto_erasure.destroy_tenant_key(tenant_id)
            receipt = DeletionReceipt(
                "del_" + uuid.uuid4().hex,
                _iso(effective_now),
                RECEIPT_VERSION,
                erasure_status,
            )
            # Explicit order is portable even where SQLite FK cascades are disabled.
            for table in (
                remediation_outcomes,
                findings,
                webhook_jobs,
                webhook_deliveries,
                github_installations,
                privacy_audit_events,
                privacy_jobs,
                migration_ledger,
                scans,
                projects,
                tenant_retention_policies,
                tenant_lifecycle,
            ):
                connection.execute(delete(table).where(table.c.tenant_id == tenant_id))
            connection.execute(delete(tenants).where(tenants.c.tenant_id == tenant_id))
            connection.execute(
                insert(deletion_receipts).values(
                    receipt_id=receipt.receipt_id,
                    request_fingerprint=fingerprint,
                    completed_at=receipt.completed_at,
                    schema_version=receipt.schema_version,
                    crypto_erasure_status=receipt.crypto_erasure_status,
                )
            )
        return receipt

    @staticmethod
    def _audit(
        connection: Any,
        tenant_id: str,
        action: str,
        resource_id: str | None,
        success: bool,
    ) -> None:
        connection.execute(
            insert(privacy_audit_events).values(
                tenant_id=tenant_id,
                event_id="audit_" + uuid.uuid4().hex,
                action=action,
                resource_id=resource_id,
                occurred_at=_iso(_now()),
                success=success,
            )
        )
