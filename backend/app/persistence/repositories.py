"""SQLAlchemy repositories implementing the existing persistence contracts."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, and_, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.github_app import (
    GitHubInstallation,
    WebhookAuditRecord,
    WebhookScanJob,
)
from app.history import ScanRecord
from app.ml.outcomes.schema import RemediationOutcome
from app.persistence.crypto import EncryptionProvider, checkout_path_aad
from app.persistence.schema import (
    findings,
    github_installations,
    projects,
    remediation_outcomes,
    scans,
    tenants,
    webhook_deliveries,
    webhook_jobs,
)
from app.projects import ProjectRecord
from app.security.tenant import current_tenant_id


def _tenant(connection: Any, tenant_id: str) -> None:
    if connection.execute(
        select(tenants.c.tenant_id).where(tenants.c.tenant_id == tenant_id)
    ).first():
        return
    try:
        with connection.begin_nested():
            connection.execute(insert(tenants).values(tenant_id=tenant_id))
    except IntegrityError:
        pass


class SqlHistoryStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _append(self, connection: Any, record: ScanRecord) -> None:
        if record.tenant_id != current_tenant_id():
            raise PermissionError("Cannot persist a scan for another tenant")
        _tenant(connection, record.tenant_id)
        aggregate = record.to_dict()
        raw_findings = aggregate.pop("findings")
        connection.execute(
            insert(scans).values(
                tenant_id=record.tenant_id,
                scan_id=record.scan_id,
                repository_id=record.repository_id,
                repository_path=record.repository_path,
                scanned_at=record.scanned_at,
                schema_version=record.schema_version,
                scoring_version=record.scoring_version,
                score=record.score,
                grade=record.grade,
                total_debt_points=record.total_debt_points,
                finding_count=record.finding_count,
                aggregates=aggregate,
            )
        )
        if raw_findings:
            connection.execute(
                insert(findings),
                [
                    {
                        "tenant_id": record.tenant_id,
                        "finding_row_id": uuid.uuid4().hex,
                        "scan_id": record.scan_id,
                        "finding_id": item["id"],
                        "ordinal": ordinal,
                        "payload": item,
                    }
                    for ordinal, item in enumerate(raw_findings)
                ],
            )

    def append(self, record: ScanRecord) -> None:
        with self.engine.begin() as connection:
            self._append(connection, record)

    def _records(self, repository_id: str | None = None) -> list[ScanRecord]:
        tenant_id = current_tenant_id()
        query = select(scans).where(scans.c.tenant_id == tenant_id)
        if repository_id is not None:
            query = query.where(scans.c.repository_id == repository_id)
        query = query.order_by(scans.c.scanned_at, scans.c.scan_id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
            result: list[ScanRecord] = []
            for row in rows:
                finding_rows = (
                    connection.execute(
                        select(findings.c.payload)
                        .where(
                            and_(
                                findings.c.tenant_id == tenant_id,
                                findings.c.scan_id == row["scan_id"],
                            )
                        )
                        .order_by(findings.c.ordinal)
                    )
                    .scalars()
                    .all()
                )
                payload = dict(row["aggregates"])
                payload["findings"] = list(finding_rows)
                result.append(ScanRecord.from_dict(payload))
            return result

    def load_all(self, repository_id: str | None = None) -> list[ScanRecord]:
        return self._records(repository_id)

    def latest(self, repository_id: str) -> ScanRecord | None:
        records = self._records(repository_id)
        return records[-1] if records else None

    def get(self, scan_id: str) -> ScanRecord | None:
        return next((item for item in self._records() if item.scan_id == scan_id), None)


class SqlProjectStore:
    def __init__(self, engine: Engine, encryption: EncryptionProvider) -> None:
        self.engine = engine
        self.encryption = encryption

    def _to_record(self, row: Any) -> ProjectRecord:
        tenant_id = str(row["tenant_id"])
        project_id = str(row["project_id"])
        path = self.encryption.decrypt(
            row["checkout_path_ciphertext"], aad=checkout_path_aad(tenant_id, project_id)
        )
        return ProjectRecord(
            project_id=project_id,
            provider=row["provider"],
            owner=row["owner"],
            name=row["name"],
            default_branch=row["default_branch"],
            connected_at=row["connected_at"],
            local_checkout_path=path,
            latest_scan_id=row["latest_scan_id"],
            latest_score=row["latest_score"],
            provider_repository_id=row["provider_repository_id"],
            provider_installation_id=row["provider_installation_id"],
            tenant_id=tenant_id,
        )

    def list(self) -> list[ProjectRecord]:
        tenant_id = current_tenant_id()
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(projects)
                    .where(projects.c.tenant_id == tenant_id)
                    .order_by(projects.c.project_id)
                )
                .mappings()
                .all()
            )
        return [self._to_record(row) for row in rows]

    def get(self, project_id: str) -> ProjectRecord | None:
        return next((item for item in self.list() if item.project_id == project_id), None)

    def _upsert(self, connection: Any, record: ProjectRecord) -> ProjectRecord:
        tenant_id = current_tenant_id()
        _tenant(connection, tenant_id)
        bound = replace(record, tenant_id=tenant_id)
        values = {
            **{
                key: value
                for key, value in asdict(bound).items()
                if key not in {"local_checkout_path"}
            },
            "checkout_path_ciphertext": self.encryption.encrypt(
                bound.local_checkout_path, aad=checkout_path_aad(tenant_id, bound.project_id)
            ),
            "encryption_provider": self.encryption.provider_name,
        }
        existing = connection.execute(
            select(projects.c.project_id).where(
                and_(projects.c.tenant_id == tenant_id, projects.c.project_id == bound.project_id)
            )
        ).first()
        if existing:
            connection.execute(
                update(projects)
                .where(
                    and_(
                        projects.c.tenant_id == tenant_id, projects.c.project_id == bound.project_id
                    )
                )
                .values(**values)
            )
        else:
            connection.execute(insert(projects).values(**values))
        return bound

    def upsert(self, record: ProjectRecord) -> ProjectRecord:
        with self.engine.begin() as connection:
            return self._upsert(connection, record)

    def record_scan(self, project_id: str, *, scan_id: str, score: int) -> ProjectRecord:
        tenant_id = current_tenant_id()
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(projects)
                .where(and_(projects.c.tenant_id == tenant_id, projects.c.project_id == project_id))
                .values(latest_scan_id=scan_id, latest_score=score)
            )
            if changed.rowcount != 1:
                raise LookupError("Project not found")
        record = self.get(project_id)
        if record is None:
            raise LookupError("Project not found")
        return record


class SqlGitHubInstallationStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self) -> list[GitHubInstallation]:
        tenant_id = current_tenant_id()
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(github_installations).where(
                        github_installations.c.tenant_id == tenant_id
                    )
                )
                .mappings()
                .all()
            )
        return [
            GitHubInstallation(**{**dict(row), "installation_id": int(row["installation_id"])})
            for row in rows
        ]

    def get(self, installation_id: int) -> GitHubInstallation | None:
        return next((item for item in self.list() if item.installation_id == installation_id), None)

    def tenant_for_installation(self, installation_id: int) -> str | None:
        with self.engine.connect() as connection:
            values = set(
                connection.execute(
                    select(github_installations.c.tenant_id).where(
                        github_installations.c.installation_id == str(installation_id)
                    )
                )
                .scalars()
                .all()
            )
        return next(iter(values)) if len(values) == 1 else None

    def upsert(self, record: GitHubInstallation) -> GitHubInstallation:
        tenant_id = current_tenant_id()
        bound = replace(record, tenant_id=tenant_id)
        values = asdict(bound)
        values["installation_id"] = str(record.installation_id)
        with self.engine.begin() as connection:
            _tenant(connection, tenant_id)
            connection.execute(
                delete(github_installations).where(
                    and_(
                        github_installations.c.tenant_id == tenant_id,
                        github_installations.c.installation_id == str(record.installation_id),
                    )
                )
            )
            connection.execute(insert(github_installations).values(**values))
        return bound

    def remove(self, installation_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(github_installations).where(
                    and_(
                        github_installations.c.tenant_id == current_tenant_id(),
                        github_installations.c.installation_id == str(installation_id),
                    )
                )
            )


class SqlWebhookAuditStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def has_delivery(self, delivery_id: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(webhook_deliveries.c.delivery_id).where(
                        and_(
                            webhook_deliveries.c.tenant_id == current_tenant_id(),
                            webhook_deliveries.c.delivery_id == delivery_id,
                        )
                    )
                ).first()
                is not None
            )

    def claim(self, record: WebhookAuditRecord) -> bool:
        tenant_id = current_tenant_id()
        bound = replace(record, tenant_id=tenant_id)
        try:
            with self.engine.begin() as connection:
                _tenant(connection, tenant_id)
                connection.execute(
                    insert(webhook_deliveries).values(
                        tenant_id=tenant_id, delivery_id=record.delivery_id, payload=asdict(bound)
                    )
                )
            return True
        except IntegrityError:
            return False

    def append(self, record: WebhookAuditRecord) -> None:
        if not self.claim(record):
            raise FileExistsError("Webhook delivery exists")

    def update(self, delivery_id: str, **changes: Any) -> WebhookAuditRecord:
        current = next(
            (item for item in self.list(100000) if item.delivery_id == delivery_id), None
        )
        if current is None:
            raise LookupError("Webhook delivery not found")
        updated = replace(current, **changes)
        with self.engine.begin() as connection:
            connection.execute(
                update(webhook_deliveries)
                .where(
                    and_(
                        webhook_deliveries.c.tenant_id == current_tenant_id(),
                        webhook_deliveries.c.delivery_id == delivery_id,
                    )
                )
                .values(payload=asdict(updated))
            )
        return updated

    def list(self, limit: int = 50) -> list[WebhookAuditRecord]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(webhook_deliveries.c.payload).where(
                        webhook_deliveries.c.tenant_id == current_tenant_id()
                    )
                )
                .scalars()
                .all()
            )
        return [WebhookAuditRecord(**row) for row in rows[-limit:]]


class SqlWebhookScanJobStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, job_id: str) -> WebhookScanJob | None:
        with self.engine.connect() as connection:
            payload = connection.execute(
                select(webhook_jobs.c.payload).where(
                    and_(
                        webhook_jobs.c.tenant_id == current_tenant_id(),
                        webhook_jobs.c.job_id == job_id,
                    )
                )
            ).scalar_one_or_none()
        return WebhookScanJob(**payload) if payload else None

    def enqueue(
        self, *, delivery_id: str, project_id: str, installation_id: int | None
    ) -> WebhookScanJob:
        tenant_id = current_tenant_id()
        material = f"{tenant_id}:{delivery_id}:{project_id}"
        job_id = "ghjob_" + hashlib.sha256(material.encode()).hexdigest()[:24]
        existing = self.get(job_id)
        if existing:
            return existing
        now = datetime.now(timezone.utc).isoformat()
        job = WebhookScanJob(
            job_id,
            delivery_id,
            project_id,
            installation_id,
            "queued",
            now,
            now,
            tenant_id=tenant_id,
        )
        with self.engine.begin() as connection:
            connection.execute(
                insert(webhook_jobs).values(
                    tenant_id=tenant_id,
                    job_id=job_id,
                    delivery_id=delivery_id,
                    project_id=project_id,
                    payload=asdict(job),
                    state="queued",
                )
            )
        return job

    def claim_queued(
        self, job_id: str, *, worker_id: str = "in-process", lease_seconds: int = 300
    ) -> bool:
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(webhook_jobs)
                .where(
                    and_(
                        webhook_jobs.c.tenant_id == current_tenant_id(),
                        webhook_jobs.c.job_id == job_id,
                        webhook_jobs.c.state == "queued",
                    )
                )
                .values(state="running", lease_owner=worker_id, lease_expires_at=expires)
            )
            return result.rowcount == 1

    def update(self, job_id: str, **changes: Any) -> WebhookScanJob:
        current = self.get(job_id)
        if current is None:
            raise LookupError("Webhook scan job not found")
        updated = replace(current, updated_at=datetime.now(timezone.utc).isoformat(), **changes)
        with self.engine.begin() as connection:
            connection.execute(
                update(webhook_jobs)
                .where(
                    and_(
                        webhook_jobs.c.tenant_id == current_tenant_id(),
                        webhook_jobs.c.job_id == job_id,
                    )
                )
                .values(payload=asdict(updated), state=updated.state)
            )
        return updated


class SqlOutcomeStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, outcome: RemediationOutcome) -> None:
        tenant_id = current_tenant_id()
        try:
            with self.engine.begin() as connection:
                _tenant(connection, tenant_id)
                connection.execute(
                    insert(remediation_outcomes).values(
                        tenant_id=tenant_id,
                        outcome_id=outcome.outcome_id,
                        repository_id=outcome.repository_id,
                        before_scan_id=outcome.before_scan_id,
                        after_scan_id=outcome.after_scan_id,
                        payload=outcome.to_dict(),
                    )
                )
        except IntegrityError as exc:
            raise FileExistsError("Remediation outcome exists") from exc

    def load_all(self, repository_id: str | None = None) -> list[RemediationOutcome]:
        query = select(remediation_outcomes.c.payload).where(
            remediation_outcomes.c.tenant_id == current_tenant_id()
        )
        if repository_id:
            query = query.where(remediation_outcomes.c.repository_id == repository_id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).scalars().all()
        return sorted(
            (RemediationOutcome.from_dict(row) for row in rows),
            key=lambda x: (x.attempted_at, x.outcome_id),
        )

    def get(self, outcome_id: str) -> RemediationOutcome | None:
        return next((item for item in self.load_all() if item.outcome_id == outcome_id), None)
