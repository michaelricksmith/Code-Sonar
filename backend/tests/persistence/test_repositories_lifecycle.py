"""SQL repository unit tests — job, outcome, compliance, and user stores.

Companion to ``tests/persistence/test_repositories.py`` (which covers
``SqlHistoryStore``, ``SqlProjectStore``, and
``SqlGitHubInstallationStore``). This file covers the remaining stores
against a sqlite database built from the real schema: the webhook
audit/scan-job stores, the outcome and compliance-record stores, the
``SqlUserStore`` lifecycle helpers, the legacy JSON import, and the
module-level identity helpers.

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
from sqlalchemy import (
    Engine,
    create_engine,
)

from app.github_app import WebhookAuditRecord
from app.ml.outcomes.schema import RemediationOutcome
from app.models.user import (
    STATUS_ACTIVE,
    STATUS_SUSPENDED,
)
from app.oauth import OAuthUser
from app.persistence.crypto import LocalDevelopmentEncryptionProvider
from app.persistence.repositories import (
    SqlComplianceRecordStore,
    SqlOutcomeStore,
    SqlUserStore,
    SqlWebhookAuditStore,
    SqlWebhookScanJobStore,
    _effective_identity,
    _identity_columns,
    _normalize_email,
    _utcnow_iso,
)
from app.persistence.schema import metadata
from app.security.tenant import (
    bind_tenant,
    reset_tenant,
)

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
def _audit(delivery_id: str = "d-1") -> WebhookAuditRecord:
    return WebhookAuditRecord(
        delivery_id=delivery_id,
        event="push",
        action=None,
        repository_full_name="octo/example",
        installation_id=123,
        project_id="project-1",
        accepted=True,
        scan_triggered=False,
        received_at="2026-09-01T00:00:00+00:00",
    )
def _outcome(
    outcome_id: str, attempted_at: str, repository_id: str = "repo-1"
) -> RemediationOutcome:
    return RemediationOutcome(
        outcome_id=outcome_id,
        repository_id=repository_id,
        finding_id="f-1",
        before_scan_id="s-before",
        after_scan_id="s-after",
        attempted_at=attempted_at,
        executor="test",
        remediation_kind="manual",
        build_passed=True,
        tests_passed=True,
        finding_resolved=True,
    )
def _github_user(store: SqlUserStore, **overrides: Any) -> OAuthUser:
    values: dict[str, Any] = {
        "provider": "github",
        "provider_user_id": "gh-1",
        "name": "Mike S",
        "email": "mike@example.com",
        "avatar_url": "https://img/x.png",
        "github_access_token": "gh-token-1",
        "github_username": "mikes",
    }
    values.update(overrides)
    return store.upsert(**values)
class TestSqlWebhookAuditStore:
    def test_claim_registers_delivery(self, engine: Engine) -> None:
        store = SqlWebhookAuditStore(engine)
        assert store.has_delivery("d-1") is False
        assert store.claim(_audit("d-1")) is True
        assert store.has_delivery("d-1") is True

    def test_claim_is_idempotent_for_duplicates(self, engine: Engine) -> None:
        store = SqlWebhookAuditStore(engine)
        assert store.claim(_audit("d-1")) is True
        assert store.claim(_audit("d-1")) is False

    def test_append_duplicate_raises_file_exists(self, engine: Engine) -> None:
        store = SqlWebhookAuditStore(engine)
        store.append(_audit("d-1"))
        with pytest.raises(FileExistsError):
            store.append(_audit("d-1"))

    def test_update_applies_changes(self, engine: Engine) -> None:
        store = SqlWebhookAuditStore(engine)
        store.append(_audit("d-1"))
        updated = store.update("d-1", outcome="processed")
        assert updated.outcome == "processed"
        assert updated.delivery_id == "d-1"

    def test_update_unknown_delivery_raises(self, engine: Engine) -> None:
        store = SqlWebhookAuditStore(engine)
        with pytest.raises(LookupError):
            store.update("missing", outcome="processed")

    def test_list_respects_limit(self, engine: Engine) -> None:
        store = SqlWebhookAuditStore(engine)
        store.append(_audit("d-1"))
        store.append(_audit("d-2"))
        store.append(_audit("d-3"))
        assert len(store.list()) == 3
        assert len(store.list(2)) == 2
class TestSqlWebhookScanJobStore:
    def test_enqueue_creates_queued_job(self, engine: Engine) -> None:
        store = SqlWebhookScanJobStore(engine)
        job = store.enqueue(delivery_id="d-1", project_id="project-1", installation_id=123)
        assert job.job_id.startswith("ghjob_")
        assert job.state == "queued"
        assert job.delivery_id == "d-1"
        assert job.project_id == "project-1"
        assert job.installation_id == 123
        assert job.tenant_id == TENANT

    def test_enqueue_is_idempotent_for_same_inputs(self, engine: Engine) -> None:
        store = SqlWebhookScanJobStore(engine)
        first = store.enqueue(delivery_id="d-1", project_id="project-1", installation_id=None)
        second = store.enqueue(delivery_id="d-1", project_id="project-1", installation_id=999)
        assert first.job_id == second.job_id

    def test_get_returns_none_for_unknown_job(self, engine: Engine) -> None:
        assert SqlWebhookScanJobStore(engine).get("ghjob_missing") is None

    def test_claim_queued_leases_job_once(self, engine: Engine) -> None:
        store = SqlWebhookScanJobStore(engine)
        job = store.enqueue(delivery_id="d-1", project_id="project-1", installation_id=None)
        assert store.claim_queued(job.job_id) is True
        assert store.claim_queued(job.job_id) is False

    def test_claim_queued_unknown_job_returns_false(self, engine: Engine) -> None:
        assert SqlWebhookScanJobStore(engine).claim_queued("ghjob_missing") is False

    def test_update_applies_state_change(self, engine: Engine) -> None:
        store = SqlWebhookScanJobStore(engine)
        job = store.enqueue(delivery_id="d-1", project_id="project-1", installation_id=None)
        updated = store.update(job.job_id, state="running", score=800)
        assert updated.state == "running"
        assert updated.score == 800
        reloaded = store.get(job.job_id)
        assert reloaded is not None
        assert reloaded.state == "running"

    def test_update_unknown_job_raises(self, engine: Engine) -> None:
        store = SqlWebhookScanJobStore(engine)
        with pytest.raises(LookupError):
            store.update("ghjob_missing", state="running")
class TestSqlOutcomeStore:
    def test_append_and_load_round_trip(self, engine: Engine) -> None:
        store = SqlOutcomeStore(engine)
        store.append(_outcome("o-1", "2026-09-01T00:00:00+00:00"))
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].outcome_id == "o-1"
        assert loaded[0].finding_resolved is True
        assert loaded[0].repository_id == "repo-1"

    def test_duplicate_append_raises_file_exists(self, engine: Engine) -> None:
        store = SqlOutcomeStore(engine)
        store.append(_outcome("o-1", "2026-09-01T00:00:00+00:00"))
        with pytest.raises(FileExistsError):
            store.append(_outcome("o-1", "2026-09-02T00:00:00+00:00"))

    def test_load_all_sorts_by_attempted_at(self, engine: Engine) -> None:
        store = SqlOutcomeStore(engine)
        store.append(_outcome("o-2", "2026-09-03T00:00:00+00:00"))
        store.append(_outcome("o-1", "2026-09-01T00:00:00+00:00"))
        loaded = store.load_all()
        assert loaded[0].outcome_id == "o-1"
        assert loaded[1].outcome_id == "o-2"

    def test_load_all_filters_by_repository(self, engine: Engine) -> None:
        store = SqlOutcomeStore(engine)
        store.append(_outcome("o-1", "2026-09-01T00:00:00+00:00", repository_id="repo-1"))
        store.append(_outcome("o-2", "2026-09-01T00:00:00+00:00", repository_id="repo-2"))
        filtered = store.load_all("repo-2")
        assert len(filtered) == 1
        assert filtered[0].outcome_id == "o-2"

    def test_get_finds_outcome_and_misses_unknown(self, engine: Engine) -> None:
        store = SqlOutcomeStore(engine)
        store.append(_outcome("o-1", "2026-09-01T00:00:00+00:00"))
        found = store.get("o-1")
        assert found is not None
        assert found.outcome_id == "o-1"
        assert store.get("missing") is None
class TestSqlComplianceRecordStore:
    def test_append_returns_record_with_payload(self, engine: Engine) -> None:
        store = SqlComplianceRecordStore(engine)
        record = store.append(user_id="u-1", record_type="consent", payload={"v": 1})
        assert record.record_id
        assert record.user_id == "u-1"
        assert record.record_type == "consent"
        assert record.payload == {"v": 1}

    def test_append_defaults_payload_to_empty_dict(self, engine: Engine) -> None:
        store = SqlComplianceRecordStore(engine)
        record = store.append(user_id="u-1", record_type="consent")
        assert record.payload == {}

    def test_latest_returns_most_recent_type(self, engine: Engine) -> None:
        store = SqlComplianceRecordStore(engine)
        store.append(user_id="u-1", record_type="erase")
        time.sleep(1.1)
        store.append(user_id="u-1", record_type="consent")
        latest = store.latest("u-1", "consent")
        assert latest is not None
        assert latest.record_type == "consent"

    def test_latest_returns_none_for_unknown(self, engine: Engine) -> None:
        store = SqlComplianceRecordStore(engine)
        store.append(user_id="u-1", record_type="consent")
        assert store.latest("u-1", "erase") is None
        assert store.latest("u-2", "consent") is None

    def test_history_orders_and_filters_by_type(self, engine: Engine) -> None:
        store = SqlComplianceRecordStore(engine)
        store.append(user_id="u-1", record_type="consent")
        time.sleep(1.1)
        store.append(user_id="u-1", record_type="erase")
        time.sleep(1.1)
        store.append(user_id="u-1", record_type="consent")
        all_records = store.history("u-1")
        assert len(all_records) == 3
        assert all_records[0].record_type == "consent"
        assert all_records[1].record_type == "erase"
        assert all_records[2].record_type == "consent"
        assert len(store.history("u-1", "erase")) == 1
class TestSqlUserStoreExtras:
    def test_set_status_rejects_unknown_status(self, engine: Engine, crypto: Any) -> None:
        store = SqlUserStore(engine, crypto)
        user = _github_user(store)
        with pytest.raises(ValueError):
            store.set_status(user.id, "banned")

    def test_admin_plan_and_status_helpers_raise_for_unknown_user(
        self, engine: Engine, crypto: Any
    ) -> None:
        store = SqlUserStore(engine, crypto)
        with pytest.raises(LookupError):
            store.set_status("missing", STATUS_ACTIVE)
        with pytest.raises(LookupError):
            store.set_admin("missing", True)
        with pytest.raises(LookupError):
            store.set_plan("missing", "pro")

    def test_set_status_round_trip(self, engine: Engine, crypto: Any) -> None:
        store = SqlUserStore(engine, crypto)
        user = _github_user(store)
        updated = store.set_status(user.id, STATUS_SUSPENDED)
        assert updated.status == STATUS_SUSPENDED
        assert updated.is_suspended is True

    def test_set_admin_and_plan_round_trip(self, engine: Engine, crypto: Any) -> None:
        store = SqlUserStore(engine, crypto)
        user = _github_user(store)
        promoted = store.set_admin(user.id, True)
        assert promoted.is_admin is True
        planned = store.set_plan(user.id, "pro")
        assert planned.plan == "pro"

    def test_set_billing_returns_none_for_unknown_user(
        self, engine: Engine, crypto: Any
    ) -> None:
        store = SqlUserStore(engine, crypto)
        assert store.set_billing("missing", plan="pro", stripe_customer_id="cus_1") is None

    def test_set_billing_preserves_stripe_id_when_empty(
        self, engine: Engine, crypto: Any
    ) -> None:
        store = SqlUserStore(engine, crypto)
        user = _github_user(store)
        first = store.set_billing(user.id, plan="pro", stripe_customer_id="cus_1")
        assert first is not None
        assert first.stripe_customer_id == "cus_1"
        second = store.set_billing(user.id, plan="pro", stripe_customer_id="")
        assert second is not None
        assert second.stripe_customer_id == "cus_1"
        assert second.plan == "pro"

    def test_scrub_underage_missing_returns_false(self, engine: Engine, crypto: Any) -> None:
        assert SqlUserStore(engine, crypto).scrub_underage("missing") is False

    def test_scrub_underage_deletes_user(self, engine: Engine, crypto: Any) -> None:
        store = SqlUserStore(engine, crypto)
        user = _github_user(store)
        assert store.scrub_underage(user.id) is True
        assert store.get(user.id) is None
        assert store.count() == 0

    def test_list_users_paginates(self, engine: Engine, crypto: Any) -> None:
        store = SqlUserStore(engine, crypto)
        _github_user(store, provider_user_id="gh-1", email="a@example.com")
        _github_user(store, provider_user_id="gh-2", email="b@example.com")
        assert store.count() == 2
        assert len(store.list_users(limit=1)) == 1
        assert len(store.list_users(limit=1, offset=1)) == 1

    def test_get_by_email_normalizes_case_and_rejects_blank(
        self, engine: Engine, crypto: Any
    ) -> None:
        store = SqlUserStore(engine, crypto)
        _github_user(store, email="Mike@Example.com")
        found = store.get_by_email("mike@example.com")
        assert found is not None
        assert found.email == "mike@example.com"
        assert store.get_by_email("") is None
        assert store.get_by_email("   ") is None

    def test_same_email_links_google_account(self, engine: Engine, crypto: Any) -> None:
        store = SqlUserStore(engine, crypto)
        github = _github_user(store)
        google = store.upsert(
            provider="google",
            provider_user_id="go-9",
            name="Mike S",
            email="MIKE@example.com",
            avatar_url="https://img/x.png",
        )
        assert google.id == github.id
        assert google.google_sub == "go-9"
        assert store.count() == 1

    def test_undecryptable_token_does_not_break_sign_in(
        self, engine: Engine, crypto: Any
    ) -> None:
        store = SqlUserStore(engine, crypto)
        user = _github_user(store)
        rotated = SqlUserStore(engine, LocalDevelopmentEncryptionProvider(b"z" * 32))
        reloaded = rotated.get(user.id)
        assert reloaded is not None
        assert reloaded.github_access_token == ""
class TestModuleHelpers:
    def test_normalize_email(self) -> None:
        assert _normalize_email("  MiKe@Example.COM ") == "mike@example.com"

    def test_normalize_email_blank_returns_none(self) -> None:
        assert _normalize_email("") is None
        assert _normalize_email("   ") is None

    def test_identity_columns(self) -> None:
        github = _identity_columns("github", "gh-1", "mikes")
        assert github["github_id"] == "gh-1"
        assert github["github_username"] == "mikes"
        assert _identity_columns("google", "go-9") == {"google_sub": "go-9"}
        assert _identity_columns("sso", "x") == {}

    def test_effective_identity_legacy_github_record(self) -> None:
        record = OAuthUser(
            id="u-1",
            provider="github",
            provider_user_id="gh-legacy",
            name="",
            email="",
            avatar_url="",
        )
        identity = _effective_identity(record)
        assert identity["github_id"] == "gh-legacy"
        assert identity["google_sub"] is None

    def test_effective_identity_prefers_explicit_columns(self) -> None:
        record = OAuthUser(
            id="u-1",
            provider="github",
            provider_user_id="gh-legacy",
            name="",
            email="",
            avatar_url="",
            github_id="gh-explicit",
            google_sub="go-explicit",
        )
        identity = _effective_identity(record)
        assert identity["github_id"] == "gh-explicit"
        assert identity["google_sub"] == "go-explicit"

    def test_utcnow_iso_format(self) -> None:
        stamp = _utcnow_iso()
        assert "T" in stamp
        assert stamp.endswith("+00:00")

    def test_import_legacy_json_missing_path_returns_zero(
        self, engine: Engine, crypto: Any, tmp_path: Path
    ) -> None:
        store = SqlUserStore(engine, crypto)
        assert store.import_legacy_json(tmp_path / "nope.json") == 0

    def test_import_legacy_json_merges_shared_email(
        self, engine: Engine, crypto: Any, tmp_path: Path
    ) -> None:
        store = SqlUserStore(engine, crypto)
        path = tmp_path / "oauth-users.json"
        path.write_text(
            json.dumps([
                asdict(
                    OAuthUser(
                        id="legacy-gh",
                        provider="github",
                        provider_user_id="gh-7",
                        name="Mike",
                        email="mike@example.com",
                        avatar_url="",
                    )
                ),
                asdict(
                    OAuthUser(
                        id="legacy-go",
                        provider="google",
                        provider_user_id="go-8",
                        name="Mike",
                        email="mike@example.com",
                        avatar_url="",
                    )
                ),
            ])
        )
        assert store.import_legacy_json(path) == 1
        merged = store.get_by_email("mike@example.com")
        assert merged is not None
        assert merged.github_id == "gh-7"
        assert merged.google_sub == "go-8"
        assert store.count() == 1
        assert store.import_legacy_json(path) == 0

    def test_import_legacy_json_skips_when_table_not_empty(
        self, engine: Engine, crypto: Any, tmp_path: Path
    ) -> None:
        store = SqlUserStore(engine, crypto)
        _github_user(store)
        path = tmp_path / "oauth-users.json"
        path.write_text(
            json.dumps([
                asdict(
                    OAuthUser(
                        id="legacy-gh",
                        provider="github",
                        provider_user_id="gh-7",
                        name="Mike",
                        email="other@example.com",
                        avatar_url="",
                    )
                )
            ])
        )
        assert store.import_legacy_json(path) == 0
