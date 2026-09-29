"""SQL repository unit tests for ``app.persistence.repositories``.

Existing coverage this file deliberately does not repeat:

- ``test_transactional_persistence.py`` covers the ``PersistenceUnitOfWork``
  wiring, cross-tenant denial, checkout-path encryption, and the atomic
  scan-update path.
- ``test_user_store.py`` covers the ``SqlUserStore`` OAuth upsert/login
  flow end to end (identity matching, token encryption, billing API).

This module covers the gaps: the full public surface of the core SQL
stores against a sqlite database built from the real schema — ``ScanRecord``
round-trips and tenant isolation (``SqlHistoryStore``), project
upsert/update/record-scan (``SqlProjectStore``), and installation CRUD
(``SqlGitHubInstallationStore``).

Companion file ``tests/persistence/test_repositories_lifecycle.py``
covers the remaining stores (webhook audit/scan-job, outcome,
compliance-record), the ``SqlUserStore`` lifecycle helpers, the legacy
JSON import, and the module-level identity helpers.

No network, no real SMTP, no external database: every test runs against a
fresh per-test sqlite file with a bound tenant.
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine

from app.github_app import GitHubInstallation, WebhookAuditRecord
from app.history import SCHEMA_VERSION, FindingSnapshot, ScanRecord
from app.ml.outcomes.schema import RemediationOutcome
from app.models.user import STATUS_ACTIVE, STATUS_SUSPENDED
from app.oauth import OAuthUser
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.repositories import (
    SqlComplianceRecordStore,
    SqlGitHubInstallationStore,
    SqlHistoryStore,
    SqlOutcomeStore,
    SqlProjectStore,
    SqlUserStore,
    SqlWebhookAuditStore,
    SqlWebhookScanJobStore,
    _effective_identity,
    _identity_columns,
    _normalize_email,
    _utcnow_iso,
)
from app.persistence.schema import metadata
from app.projects import ProjectRecord
from app.security.tenant import bind_tenant, reset_tenant

TENANT = "tenant-a"


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine, None, None]:
    token = bind_tenant(TENANT)
    eng = create_engine(f"sqlite:///{tmp_path / 'repos.db'}")
    metadata.create_all(eng)
    yield eng
    reset_tenant(token)
    eng.dispose()


@pytest.fixture
def crypto() -> LocalDevelopmentEncryptionProvider:
    return LocalDevelopmentEncryptionProvider(b"k" * 32)


def _finding(fid: str) -> FindingSnapshot:
    return FindingSnapshot.from_dict({
        "id": fid,
        "rule_id": "test:rule",
        "category": "maintainability",
        "severity": "warning",
        "confidence": 1.0,
        "file_path": "src/app.py",
        "line_start": 1,
        "line_end": 1,
        "symbol": None,
        "evidence": "",
        "message": f"finding {fid}",
        "suggestion": None,
        "debt_points": 4,
        "analyzer": "test_analyzer",
        "metadata": {},
    })


def _scan(
    scan_id: str,
    *,
    repository_id: str = "repo-1",
    scanned_at: str = "2026-09-02T00:00:00+00:00",
    findings: list[FindingSnapshot] | None = None,
    tenant_id: str = TENANT,
) -> ScanRecord:
    snaps = findings if findings is not None else []
    return ScanRecord.from_dict({
        "scan_id": scan_id,
        "tenant_id": tenant_id,
        "repository_id": repository_id,
        "repository_path": "repo",
        "scanned_at": scanned_at,
        "schema_version": SCHEMA_VERSION,
        "score": 720,
        "grade": "B",
        "total_debt_points": 10,
        "finding_count": len(snaps),
        "category_scores": {},
        "severity_distribution": {},
        "findings_by_category": {},
        "findings_source_breakdown": {},
        "findings": [snap.to_dict() for snap in snaps],
    })


def _project(project_id: str = "project-1", **overrides: Any) -> ProjectRecord:
    fields: dict[str, Any] = {
        "project_id": project_id,
        "provider": "github",
        "owner": "acme",
        "name": "widget",
        "default_branch": "main",
        "connected_at": "2026-09-01T00:00:00+00:00",
        "local_checkout_path": "/tmp/checkout",
    }
    fields.update(overrides)
    return ProjectRecord(**fields)


def _installation(installation_id: int = 123) -> GitHubInstallation:
    return GitHubInstallation(
        installation_id=installation_id,
        account_login="octo",
        account_type="Organization",
        installed_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
    )


class TestSqlHistoryStore:
    def test_append_and_load_round_trip_with_findings(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1", findings=[_finding("f-1"), _finding("f-2")]))
        records = store.load_all()
        assert len(records) == 1
        assert records[0].scan_id == "s-1"
        assert records[0].repository_id == "repo-1"
        assert records[0].score == 720
        assert len(records[0].findings) == 2
        assert records[0].findings[0].id == "f-1"
        assert records[0].findings[1].id == "f-2"
        assert records[0].tenant_id == TENANT

    def test_append_without_findings_persists_scan(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1"))
        records = store.load_all()
        assert len(records) == 1
        assert records[0].findings == []

    def test_load_all_filters_by_repository(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1", repository_id="repo-1"))
        store.append(_scan("s-2", repository_id="repo-2"))
        filtered = store.load_all("repo-1")
        assert len(filtered) == 1
        assert filtered[0].scan_id == "s-1"

    def test_latest_returns_most_recent_scan(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1", scanned_at="2026-09-01T00:00:00+00:00"))
        store.append(_scan("s-2", scanned_at="2026-09-03T00:00:00+00:00"))
        latest = store.latest("repo-1")
        assert latest is not None
        assert latest.scan_id == "s-2"

    def test_latest_returns_none_when_empty(self, engine: Engine) -> None:
        assert SqlHistoryStore(engine).latest("repo-1") is None

    def test_get_returns_scan_by_id(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1"))
        found = store.get("s-1")
        assert found is not None
        assert found.scan_id == "s-1"

    def test_get_returns_none_for_unknown_id(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1"))
        assert store.get("nope") is None

    def test_append_rejects_other_tenant_record(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        with pytest.raises(PermissionError):
            store.append(_scan("s-1", tenant_id="tenant-b"))

    def test_records_are_tenant_scoped(self, engine: Engine) -> None:
        store = SqlHistoryStore(engine)
        store.append(_scan("s-1"))
        token = bind_tenant("tenant-b")
        try:
            assert store.load_all() == []
        finally:
            reset_tenant(token)


class TestSqlProjectStore:
    def test_upsert_and_get_round_trip(self, engine: Engine, crypto: Any) -> None:
        store = SqlProjectStore(engine, crypto)
        store.upsert(_project())
        record = store.get("project-1")
        assert record is not None
        assert record.project_id == "project-1"
        assert record.owner == "acme"
        assert record.name == "widget"
        assert record.local_checkout_path == "/tmp/checkout"
        assert record.provider_repository_id is None
        assert record.tenant_id == TENANT

    def test_upsert_existing_row_updates_in_place(self, engine: Engine, crypto: Any) -> None:
        store = SqlProjectStore(engine, crypto)
        store.upsert(_project())
        store.upsert(_project(name="renamed", provider_repository_id=4242))
        records = store.list()
        assert len(records) == 1
        assert records[0].name == "renamed"
        assert records[0].provider_repository_id == 4242

    def test_list_orders_by_project_id_and_scopes_tenant(
        self, engine: Engine, crypto: Any
    ) -> None:
        store = SqlProjectStore(engine, crypto)
        store.upsert(_project("project-b"))
        store.upsert(_project("project-a"))
        listed = store.list()
        assert listed[0].project_id == "project-a"
        assert listed[1].project_id == "project-b"
        token = bind_tenant("tenant-b")
        try:
            assert store.list() == []
        finally:
            reset_tenant(token)

    def test_get_returns_none_for_unknown_project(self, engine: Engine, crypto: Any) -> None:
        assert SqlProjectStore(engine, crypto).get("missing") is None

    def test_record_scan_updates_latest_fields(self, engine: Engine, crypto: Any) -> None:
        store = SqlProjectStore(engine, crypto)
        store.upsert(_project())
        updated = store.record_scan("project-1", scan_id="scan-9", score=801)
        assert updated.latest_scan_id == "scan-9"
        assert updated.latest_score == 801
        reloaded = store.get("project-1")
        assert reloaded is not None
        assert reloaded.latest_scan_id == "scan-9"

    def test_record_scan_unknown_project_raises(self, engine: Engine, crypto: Any) -> None:
        store = SqlProjectStore(engine, crypto)
        with pytest.raises(LookupError):
            store.record_scan("missing", scan_id="s", score=1)


class TestSqlGitHubInstallationStore:
    def test_upsert_and_get(self, engine: Engine) -> None:
        store = SqlGitHubInstallationStore(engine)
        store.upsert(_installation(123))
        found = store.get(123)
        assert found is not None
        assert found.installation_id == 123
        assert isinstance(found.installation_id, int)
        assert found.account_login == "octo"
        assert found.tenant_id == TENANT

    def test_upsert_replaces_existing_installation(self, engine: Engine) -> None:
        store = SqlGitHubInstallationStore(engine)
        store.upsert(_installation(123))
        renamed = GitHubInstallation(
            installation_id=123,
            account_login="renamed",
            account_type="Organization",
            installed_at="2026-09-01T00:00:00+00:00",
            updated_at="2026-09-02T00:00:00+00:00",
        )
        store.upsert(renamed)
        assert len(store.list()) == 1
        found = store.get(123)
        assert found is not None
        assert found.account_login == "renamed"

    def test_remove_deletes_installation(self, engine: Engine) -> None:
        store = SqlGitHubInstallationStore(engine)
        store.upsert(_installation(123))
        store.remove(123)
        assert store.get(123) is None
        assert store.list() == []

    def test_get_returns_none_for_unknown(self, engine: Engine) -> None:
        assert SqlGitHubInstallationStore(engine).get(999) is None

    def test_tenant_for_installation(self, engine: Engine) -> None:
        store = SqlGitHubInstallationStore(engine)
        store.upsert(_installation(123))
        assert store.tenant_for_installation(123) == TENANT
        assert store.tenant_for_installation(999) is None

    def test_list_scopes_installations_to_tenant(self, engine: Engine) -> None:
        store = SqlGitHubInstallationStore(engine)
        store.upsert(_installation(123))
        token = bind_tenant("tenant-b")
        try:
            assert store.list() == []
        finally:
            reset_tenant(token)

