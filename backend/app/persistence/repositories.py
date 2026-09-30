"""SQLAlchemy repositories implementing the existing persistence contracts."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import Engine, and_, delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.compliance.records import ComplianceRecord
from app.github_app import (
    GitHubInstallation,
    WebhookAuditRecord,
    WebhookScanJob,
)
from app.history import ScanRecord
from app.ml.outcomes.schema import RemediationOutcome
from app.models.user import (
    PLAN_FREE,
    PROVIDER_GITHUB,
    PROVIDER_GOOGLE,
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
    users,
)
from app.oauth import OAuthUser, OAuthUserStore
from app.persistence.crypto import EncryptionProvider, checkout_path_aad, oauth_token_aad
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
                commit_sha=record.commit_sha,
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
                finding_rows: Sequence[Any] = (
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

    def update_owner(self, scan_id: str, owner_user_id: str) -> bool:
        """Attribute an ownerless scan; owner lives inside the aggregates JSON."""
        tenant_id = current_tenant_id()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(scans.c.aggregates).where(
                    and_(scans.c.tenant_id == tenant_id, scans.c.scan_id == scan_id)
                )
            ).first()
            if row is None:
                return False
            aggregates = dict(row[0] or {})
            aggregates["owner_user_id"] = owner_user_id
            connection.execute(
                update(scans)
                .where(and_(scans.c.tenant_id == tenant_id, scans.c.scan_id == scan_id))
                .values(aggregates=aggregates)
            )
            return True


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
            values: set[Any] = set(
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
            rows: Sequence[Any] = (
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
            rows: Sequence[Any] = connection.execute(query).scalars().all()
        return sorted(
            (RemediationOutcome.from_dict(row) for row in rows),
            key=lambda x: (x.attempted_at, x.outcome_id),
        )

    def get(self, outcome_id: str) -> RemediationOutcome | None:
        return next((item for item in self.load_all() if item.outcome_id == outcome_id), None)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email: str) -> str | None:
    normalized = (email or "").strip().lower()
    return normalized or None


def _identity_columns(
    provider: str, provider_user_id: str, github_username: str = ""
) -> dict[str, Any]:
    """Map an OAuth identity to the users-table identity columns."""
    if provider == PROVIDER_GITHUB:
        return {
            "github_id": provider_user_id or None,
            "github_username": github_username or None,
        }
    if provider == PROVIDER_GOOGLE:
        return {"google_sub": provider_user_id or None}
    return {}


def _effective_identity(record: OAuthUser) -> dict[str, Any]:
    """Resolve a (possibly legacy) user record to users-table identity columns.

    Records written before the identity columns existed only carry
    ``provider``/``provider_user_id``; fall back to those.
    """
    github_id = record.github_id or (
        record.provider_user_id if record.provider == PROVIDER_GITHUB else ""
    )
    google_sub = record.google_sub or (
        record.provider_user_id if record.provider == PROVIDER_GOOGLE else ""
    )
    return {
        "github_id": github_id or None,
        "github_username": record.github_username or None,
        "google_sub": google_sub or None,
    }


def _coalesce(value: Any, default: Any) -> Any:
    """Return ``value`` unless it is falsy, in which case return ``default``."""
    return value or default


def _row_provider_user_id(row: RowMapping, provider: str) -> str:
    """Resolve the provider user id stored on a users-table row."""
    if provider == PROVIDER_GITHUB:
        return row["github_id"] or ""
    if provider == PROVIDER_GOOGLE:
        return row["google_sub"] or ""
    return ""


def _merge_key(record: OAuthUser) -> str:
    """Key for merging legacy records: normalized email, else provider identity."""
    return _normalize_email(record.email) or f"{record.provider}:{record.provider_user_id}"


def _merged_legacy_record(existing: OAuthUser, record: OAuthUser) -> OAuthUser:
    """Fold a duplicate legacy record into the surviving one, preferring kept values."""
    return replace(
        existing,
        github_id=existing.github_id
        or record.github_id
        or (record.provider_user_id if record.provider == PROVIDER_GITHUB else ""),
        github_username=existing.github_username or record.github_username,
        google_sub=existing.google_sub
        or record.google_sub
        or (record.provider_user_id if record.provider == PROVIDER_GOOGLE else ""),
        github_access_token=existing.github_access_token or record.github_access_token,
    )


def _merge_legacy(legacy: list[OAuthUser]) -> tuple[dict[str, OAuthUser], list[str]]:
    """Merge legacy records sharing an email into one account per merge key."""
    merged: dict[str, OAuthUser] = {}
    order: list[str] = []
    for record in legacy:
        key = _merge_key(record)
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            order.append(key)
            continue
        merged[key] = _merged_legacy_record(existing, record)
    return merged, order


class SqlUserStore:
    """Database-backed user accounts.

    This is the source of truth for user accounts whenever SQL persistence
    is configured; ``app.oauth`` swaps it in as the process-wide user store
    at startup. The ``get``/``upsert`` interface mirrors ``OAuthUserStore``
    so the OAuth callbacks work unchanged.

    A user may link both GitHub and Google to one account: sign-ins are
    matched by provider identity first, then by normalized email, so the
    same email can never fork into two accounts.
    """

    def __init__(self, engine: Engine, encryption: EncryptionProvider) -> None:
        self.engine = engine
        self.encryption = encryption

    # -- mapping ------------------------------------------------------

    def _encrypt_token(self, user_id: str, token: str) -> str | None:
        if not token:
            return None
        return self.encryption.encrypt(token, aad=oauth_token_aad(user_id))

    def _decrypt_row_token(self, row: RowMapping) -> str:
        """Decrypt the stored GitHub token; an undecryptable token reads as empty."""
        ciphertext = row["github_token_ciphertext"]
        if not ciphertext:
            return ""
        try:
            return self.encryption.decrypt(ciphertext, aad=oauth_token_aad(row["id"]))
        except Exception:
            # A token that can no longer decrypt (e.g. key rotation)
            # must not break sign-in; the user re-links on next OAuth.
            return ""

    def _row_to_user(self, row: RowMapping) -> OAuthUser:
        provider = _coalesce(row["provider"], "")
        return OAuthUser(
            id=row["id"],
            provider=provider,
            provider_user_id=_row_provider_user_id(row, provider),
            name=_coalesce(row["display_name"], ""),
            email=_coalesce(row["email"], ""),
            avatar_url=_coalesce(row["avatar_url"], ""),
            github_access_token=self._decrypt_row_token(row),
            created_at=_coalesce(row["created_at"], ""),
            updated_at=_coalesce(row["updated_at"], ""),
            github_id=_coalesce(row["github_id"], ""),
            github_username=_coalesce(row["github_username"], ""),
            google_sub=_coalesce(row["google_sub"], ""),
            plan=_coalesce(row["plan"], PLAN_FREE),
            stripe_customer_id=_coalesce(row["stripe_customer_id"], ""),
            status=_coalesce(row["status"], STATUS_ACTIVE),
            is_admin=bool(row["is_admin"]),
            last_login_at=_coalesce(row["last_login_at"], ""),
        )

    # -- reads --------------------------------------------------------

    def get(self, user_id: str) -> OAuthUser | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_by_email(self, email: str) -> OAuthUser | None:
        email_norm = _normalize_email(email)
        if not email_norm:
            return None
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(users).where(users.c.email == email_norm))
                .mappings()
                .first()
            )
        if row is None:
            return None
        return self._row_to_user(row)

    def count(self) -> int:
        with self.engine.connect() as connection:
            return self._count(connection)

    def _count(self, connection: Any) -> int:
        return int(connection.execute(select(func.count()).select_from(users)).scalar() or 0)

    def list_users(self, *, limit: int = 100, offset: int = 0) -> list[OAuthUser]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(users).order_by(users.c.created_at.desc()).limit(limit).offset(offset)
                )
                .mappings()
                .all()
            )
        return [self._row_to_user(row) for row in rows]

    # -- writes -------------------------------------------------------

    def _find_user_id(
        self,
        connection: Any,
        provider: str,
        provider_user_id: str,
        email_norm: str | None,
    ) -> str | None:
        identity_column = None
        if provider == PROVIDER_GITHUB:
            identity_column = users.c.github_id
        elif provider == PROVIDER_GOOGLE:
            identity_column = users.c.google_sub
        if identity_column is not None and provider_user_id:
            found = connection.execute(
                select(users.c.id).where(identity_column == provider_user_id)
            ).scalar_one_or_none()
            if found is not None:
                return str(found)
        if email_norm:
            found = connection.execute(
                select(users.c.id).where(users.c.email == email_norm)
            ).scalar_one_or_none()
            if found is not None:
                return str(found)
        return None

    def _apply_login(
        self,
        connection: Any,
        user_id: str,
        *,
        provider: str,
        provider_user_id: str,
        name: str,
        avatar_url: str,
        github_access_token: str,
        github_username: str,
        now: str,
    ) -> None:
        values: dict[str, Any] = {
            "provider": provider,
            "updated_at": now,
            "last_login_at": now,
        }
        if name:
            values["display_name"] = name
        if avatar_url:
            values["avatar_url"] = avatar_url
        values.update(_identity_columns(provider, provider_user_id, github_username))
        if github_access_token:
            values["github_token_ciphertext"] = self._encrypt_token(user_id, github_access_token)
        connection.execute(update(users).where(users.c.id == user_id).values(**values))

    def _get_or_raise(self, connection: Any, user_id: str) -> OAuthUser:
        row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
        if row is None:  # pragma: no cover - defensive
            raise LookupError("User not found")
        return self._row_to_user(row)

    def upsert(
        self,
        *,
        provider: str,
        provider_user_id: str,
        name: str,
        email: str,
        avatar_url: str,
        github_access_token: str = "",
        github_username: str = "",
    ) -> OAuthUser:
        now = _utcnow_iso()
        email_norm = _normalize_email(email)
        with self.engine.begin() as connection:
            user_id = self._find_user_id(connection, provider, provider_user_id, email_norm)
            if user_id is None:
                user_id = uuid.uuid4().hex
                values: dict[str, Any] = {
                    "id": user_id,
                    "email": email_norm,
                    "display_name": name,
                    "avatar_url": avatar_url,
                    "provider": provider,
                    "plan": PLAN_FREE,
                    "status": STATUS_ACTIVE,
                    "is_admin": False,
                    "github_token_ciphertext": self._encrypt_token(user_id, github_access_token),
                    "created_at": now,
                    "updated_at": now,
                    "last_login_at": now,
                }
                values.update(_identity_columns(provider, provider_user_id, github_username))
                try:
                    connection.execute(insert(users).values(**values))
                except IntegrityError:
                    # Lost a race with a concurrent sign-in; use the winner.
                    user_id = self._find_user_id(connection, provider, provider_user_id, email_norm)
                    if user_id is None:
                        raise
                    self._apply_login(
                        connection,
                        user_id,
                        provider=provider,
                        provider_user_id=provider_user_id,
                        name=name,
                        avatar_url=avatar_url,
                        github_access_token=github_access_token,
                        github_username=github_username,
                        now=now,
                    )
            else:
                self._apply_login(
                    connection,
                    user_id,
                    provider=provider,
                    provider_user_id=provider_user_id,
                    name=name,
                    avatar_url=avatar_url,
                    github_access_token=github_access_token,
                    github_username=github_username,
                    now=now,
                )
            return self._get_or_raise(connection, user_id)

    def set_status(self, user_id: str, status: str) -> OAuthUser:
        if status not in (STATUS_ACTIVE, STATUS_SUSPENDED):
            raise ValueError(f"Unknown user status: {status}")
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(status=status, updated_at=_utcnow_iso())
            )
            if updated.rowcount != 1:
                raise LookupError("User not found")
            return self._get_or_raise(connection, user_id)

    def set_admin(self, user_id: str, is_admin: bool) -> OAuthUser:
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(is_admin=is_admin, updated_at=_utcnow_iso())
            )
            if updated.rowcount != 1:
                raise LookupError("User not found")
            return self._get_or_raise(connection, user_id)

    def set_plan(self, user_id: str, plan: str) -> OAuthUser:
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(plan=plan, updated_at=_utcnow_iso())
            )
            if updated.rowcount != 1:
                raise LookupError("User not found")
            return self._get_or_raise(connection, user_id)

    def set_billing(self, user_id: str, *, plan: str, stripe_customer_id: str) -> OAuthUser | None:
        """Update a user's billing plan (and Stripe customer id when given).

        An empty ``stripe_customer_id`` preserves the existing value.
        Returns the updated user, or None when the user does not exist.
        """
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(users.c.id).where(users.c.id == user_id)
            ).scalar_one_or_none()
            if exists is None:
                return None
            values: dict[str, Any] = {"plan": plan, "updated_at": _utcnow_iso()}
            if stripe_customer_id:
                values["stripe_customer_id"] = stripe_customer_id
            connection.execute(update(users).where(users.c.id == user_id).values(**values))
            return self._get_or_raise(connection, user_id)

    def scrub_underage(self, user_id: str) -> bool:
        """Delete a just-created under-13 account (age-gate block).

        Removes the entire row — PII, OAuth identities, and tokens. No
        record of the signup attempt is retained.
        """
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(users.c.id).where(users.c.id == user_id)
            ).scalar_one_or_none()
            if exists is None:
                return False
            connection.execute(delete(users).where(users.c.id == user_id))
            return True

    # -- legacy import ------------------------------------------------

    def _legacy_insert_values(self, record: OAuthUser) -> dict[str, Any]:
        """Map a merged legacy record to users-table insert values."""
        return {
            "id": record.id,
            "email": _normalize_email(record.email),
            "display_name": record.name,
            "avatar_url": record.avatar_url,
            "provider": record.provider,
            "plan": record.plan or PLAN_FREE,
            "stripe_customer_id": record.stripe_customer_id or None,
            "status": record.status or STATUS_ACTIVE,
            "is_admin": bool(record.is_admin),
            "github_token_ciphertext": self._encrypt_token(record.id, record.github_access_token),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "last_login_at": record.last_login_at or None,
            **_effective_identity(record),
        }

    def import_legacy_json(self, path: Path) -> int:
        """One-time import of a legacy ``oauth-users.json`` file.

        Imports only when the users table is empty. Records sharing an
        email are merged into one account (same linking rule as upsert).
        The JSON file is left untouched. Returns the number of imported
        users.
        """
        if not path.exists():
            return 0
        legacy = OAuthUserStore(path=path).load_all()
        if not legacy:
            return 0
        merged, order = _merge_legacy(legacy)
        with self.engine.begin() as connection:
            if self._count(connection) > 0:
                return 0
            for key in order:
                record = merged[key]
                connection.execute(insert(users).values(**self._legacy_insert_values(record)))
        return len(order)


class SqlComplianceRecordStore:
    """SQL implementation of the append-only compliance record store."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(
        self, *, user_id: str, record_type: str, payload: dict[str, Any] | None = None
    ) -> ComplianceRecord:
        from app.persistence.schema import compliance_records

        record = ComplianceRecord(
            record_id=uuid.uuid4().hex,
            user_id=user_id,
            record_type=record_type,
            payload=dict(payload or {}),
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        with self.engine.begin() as connection:
            connection.execute(
                insert(compliance_records).values(
                    record_id=record.record_id,
                    user_id=record.user_id,
                    record_type=record.record_type,
                    payload=record.payload,
                    created_at=record.created_at,
                )
            )
        return record

    def latest(self, user_id: str, record_type: str) -> ComplianceRecord | None:
        from app.persistence.schema import compliance_records

        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(compliance_records)
                    .where(
                        compliance_records.c.user_id == user_id,
                        compliance_records.c.record_type == record_type,
                    )
                    .order_by(compliance_records.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return ComplianceRecord(
            record_id=row["record_id"],
            user_id=row["user_id"],
            record_type=row["record_type"],
            payload=dict(row["payload"] or {}),
            created_at=row["created_at"],
        )

    def history(self, user_id: str, record_type: str | None = None) -> list[ComplianceRecord]:
        from app.persistence.schema import compliance_records

        conditions = [compliance_records.c.user_id == user_id]
        if record_type is not None:
            conditions.append(compliance_records.c.record_type == record_type)
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(compliance_records)
                    .where(and_(*conditions))
                    .order_by(compliance_records.c.created_at.asc())
                )
                .mappings()
                .all()
            )
        return [
            ComplianceRecord(
                record_id=row["record_id"],
                user_id=row["user_id"],
                record_type=row["record_type"],
                payload=dict(row["payload"] or {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]
