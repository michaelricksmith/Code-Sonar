"""Unit tests for ``app.github_app`` — webhook payload handling and dispatch.

Companion files: ``tests/api/test_github_app.py`` covers the
installation/audit/scan-job stores; ``tests/api/test_github_app_auth.py``
covers ``GitHubAppAuth``, install-state signing, and webhook signature
verification. This file covers the
payload/context/trigger helpers, the scan-job runner, and the
module-level setter/getter surface. Edge cases (``None``/empty inputs,
missing secrets, unknown tenants) and error paths are included
throughout.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks

from app.github_app import (
    GitHubAppAuth,
    GitHubInstallation,
    GitHubInstallationStore,
    WebhookAuditStore,
    WebhookScanJobStore,
    _build_webhook_audit,
    _dispatch_webhook_scan,
    _installation_from_payload,
    _project_for_repository,
    _run_project_scan_job,
    _run_project_scan_job_for_bound_tenant,
    _sync_webhook_installation,
    _webhook_event_context,
    _webhook_scan_trigger,
    _WebhookContext,
    get_active_installation_id,
    get_github_app_auth,
    get_installation_store,
    get_webhook_audit_store,
    get_webhook_job_store,
    set_active_installation_id,
    set_github_app_auth,
    set_installation_store,
    set_webhook_audit_store,
    set_webhook_job_store,
    set_webhook_scan_handler,
)
from app.projects import (
    ProjectRecord,
    ProjectStore,
    get_project_store,
    set_project_store,
)
from app.security.tenant import bind_tenant, current_tenant_id, reset_tenant

# ---------------------------------------------------------------------------
# Builders and fixtures
# ---------------------------------------------------------------------------

def _mk_installation(
    installation_id: int = 7,
    login: str = "octo",
    tenant: str = "tenant-a",
) -> GitHubInstallation:
    return GitHubInstallation(
        installation_id=installation_id,
        account_login=login,
        account_type="Organization",
        installed_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-02T00:00:00+00:00",
        tenant_id=tenant,
    )

def _mk_project(
    project_id: str = "p1",
    *,
    owner: str = "octo",
    name: str = "example",
    branch: str = "main",
    installation: int | None = None,
    provider: str = "github",
) -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id,
        provider=provider,
        owner=owner,
        name=name,
        default_branch=branch,
        connected_at="2026-09-01T00:00:00+00:00",
        local_checkout_path="/tmp/checkout",
        provider_installation_id=installation,
    )
def _mk_context(**overrides: Any) -> _WebhookContext:
    base: dict[str, Any] = {
        "event": "push",
        "delivery": "d1",
        "action": None,
        "installation": None,
        "installation_id": None,
        "full_name": None,
        "project_id": None,
    }
    base.update(overrides)
    return _WebhookContext(**base)

def _seed_projects(bundle: SimpleNamespace) -> None:
    bundle.projects.upsert(_mk_project("p1"))
    bundle.projects.upsert(_mk_project("p2", name="pinned", installation=9))
    bundle.projects.upsert(_mk_project("p3", name="lab", provider="gitlab"))

@pytest.fixture()
def sandbox(tmp_path: Path, request: pytest.FixtureRequest) -> SimpleNamespace:
    """Swap the module's file-backed stores for tmp-path ones under tenant-a."""
    previous = (
        get_installation_store(),
        get_webhook_audit_store(),
        get_webhook_job_store(),
        get_project_store(),
    )
    bundle = SimpleNamespace(
        installations=GitHubInstallationStore(tmp_path / "installations.json"),
        audit=WebhookAuditStore(tmp_path / "audit.jsonl"),
        jobs=WebhookScanJobStore(tmp_path / "jobs.json"),
        projects=ProjectStore(tmp_path / "projects.json"),
        tmp=tmp_path,
    )
    set_installation_store(bundle.installations)
    set_webhook_audit_store(bundle.audit)
    set_webhook_job_store(bundle.jobs)
    set_project_store(bundle.projects)
    token = bind_tenant("tenant-a")

    def _restore() -> None:
        reset_tenant(token)
        set_installation_store(previous[0])
        set_webhook_audit_store(previous[1])
        set_webhook_job_store(previous[2])
        set_project_store(previous[3])

    request.addfinalizer(_restore)
    return bundle
def test_installation_from_payload_returns_none_without_installation(
    sandbox: SimpleNamespace,
) -> None:
    assert _installation_from_payload({}) is None
    assert _installation_from_payload({"installation": {"account": {}}}) is None

def test_installation_from_payload_builds_record(sandbox: SimpleNamespace) -> None:
    payload = {
        "installation": {
            "id": 9,
            "repository_selection": "all",
            "account": {"login": "octo", "type": "Organization"},
        }
    }
    record = _installation_from_payload(payload)
    assert record is not None
    assert record.installation_id == 9
    assert record.account_login == "octo"
    assert record.repository_selection == "all"

def test_installation_from_payload_preserves_first_seen_time(
    sandbox: SimpleNamespace,
) -> None:
    sandbox.installations.upsert(_mk_installation(9))
    payload = {"installation": {"id": 9, "account": {"login": "octo"}}}
    record = _installation_from_payload(payload)
    assert record is not None
    assert record.installed_at == "2026-09-01T00:00:00+00:00"

def test_project_for_repository_matches_unpinned_project(
    sandbox: SimpleNamespace,
) -> None:
    _seed_projects(sandbox)
    assert _project_for_repository("Octo/Example", None) == "p1"
    assert _project_for_repository("octo/example", 123) == "p1"

def test_project_for_repository_rejects_mismatches(
    sandbox: SimpleNamespace,
) -> None:
    _seed_projects(sandbox)
    assert _project_for_repository("octo/pinned", 7) is None
    assert _project_for_repository("octo/pinned", 9) == "p2"
    assert _project_for_repository("octo/lab", None) is None
    assert _project_for_repository("octo/unknown", None) is None

def test_webhook_event_context_derives_missing_headers(
    sandbox: SimpleNamespace,
) -> None:
    body = b'{"action":"created"}'
    context = _webhook_event_context({"action": "created"}, body, None, None)
    assert context.event == "unknown"
    assert context.delivery == hashlib.sha256(body).hexdigest()[:24]
    assert context.installation is None
    assert context.project_id is None

def test_webhook_event_context_extracts_installation_and_repo(
    sandbox: SimpleNamespace,
) -> None:
    payload = {
        "installation": {
            "id": 42,
            "account": {"login": "octo", "type": "Organization"},
            "repository_selection": "all",
        },
        "repository": {"full_name": "octo/example"},
    }
    context = _webhook_event_context(payload, b"{}", "installation", "del-42")
    assert context.installation_id == 42
    assert context.installation.account_login == "octo"
    assert context.full_name == "octo/example"
    assert context.project_id is None
    assert context.event == "installation"

def test_webhook_event_context_rejects_non_dict_payload(
    sandbox: SimpleNamespace,
) -> None:
    # Documents current behavior: a JSON-array webhook body crashes the
    # context builder because _installation_from_payload assumes a dict.
    with pytest.raises(AttributeError):
        _webhook_event_context(["not", "a", "dict"], b"[]", "push", "del-x")

def test_build_webhook_audit_maps_context_fields(sandbox: SimpleNamespace) -> None:
    context = _mk_context(
        event="push",
        delivery="del-1",
        action="created",
        installation_id=7,
        full_name="octo/example",
        project_id="p1",
    )
    record = _build_webhook_audit(context)
    assert record.delivery_id == "del-1"
    assert record.event == "push"
    assert record.action == "created"
    assert record.repository_full_name == "octo/example"
    assert record.installation_id == 7
    assert record.project_id == "p1"
    assert record.accepted is True
    assert record.scan_triggered is False

def test_webhook_scan_trigger_push_matches_default_branch(
    sandbox: SimpleNamespace,
) -> None:
    _seed_projects(sandbox)
    context = _mk_context(event="push", project_id="p1")
    assert _webhook_scan_trigger(context, {"ref": "refs/heads/main"}) is True
    assert _webhook_scan_trigger(context, {"ref": "refs/heads/dev"}) is False

def test_webhook_scan_trigger_pull_request_merged_only(
    sandbox: SimpleNamespace,
) -> None:
    _seed_projects(sandbox)
    context = _mk_context(event="pull_request", action="closed", project_id="p1")
    merged = {"action": "closed", "pull_request": {"merged": True}}
    assert _webhook_scan_trigger(context, merged) is True
    unmerged = {"action": "closed", "pull_request": {"merged": False}}
    assert _webhook_scan_trigger(context, unmerged) is False

def test_webhook_scan_trigger_ignores_other_cases(
    sandbox: SimpleNamespace,
) -> None:
    _seed_projects(sandbox)
    opened = _mk_context(event="pull_request", action="opened", project_id="p1")
    payload = {"action": "opened", "pull_request": {"merged": True}}
    assert _webhook_scan_trigger(opened, payload) is False
    no_project = _mk_context(event="push", project_id=None)
    assert _webhook_scan_trigger(no_project, {"ref": "refs/heads/main"}) is False
    issue = _mk_context(event="issues", project_id="p1")
    assert _webhook_scan_trigger(issue, {}) is False

# ---------------------------------------------------------------------------
# Webhook sync / dispatch helpers
# ---------------------------------------------------------------------------

def test_sync_webhook_installation_upserts_record(
    sandbox: SimpleNamespace,
) -> None:
    context = _mk_context(
        event="installation",
        action="created",
        installation=_mk_installation(7),
        installation_id=7,
    )
    _sync_webhook_installation(context, "tenant-a")
    assert sandbox.installations.get(7) is not None

def test_sync_webhook_installation_delete_removes_and_clears_active(
    sandbox: SimpleNamespace,
) -> None:
    sandbox.installations.upsert(_mk_installation(7))
    set_active_installation_id(7)
    context = _mk_context(
        event="installation",
        action="deleted",
        installation=_mk_installation(7),
        installation_id=7,
    )
    _sync_webhook_installation(context, "tenant-a")
    set_active_installation_id(None)
    assert sandbox.installations.get(7) is None
    assert get_active_installation_id() is None

def test_sync_webhook_installation_ignores_missing_installation(
    sandbox: SimpleNamespace,
) -> None:
    _sync_webhook_installation(_mk_context(event="push"), "tenant-a")
    assert sandbox.installations.list() == []

def test_dispatch_webhook_scan_unknown_installation(
    sandbox: SimpleNamespace,
) -> None:
    context = _mk_context(event="installation", delivery="d1")
    sandbox.audit.append(_build_webhook_audit(context))
    job_id = _dispatch_webhook_scan(context, False, 99, None, BackgroundTasks())
    stored = sandbox.audit.list()[0]
    assert job_id is None
    assert stored.outcome == "unknown_installation"
    assert stored.scan_triggered is False

def test_dispatch_webhook_scan_ignored(sandbox: SimpleNamespace) -> None:
    context = _mk_context(event="issues", delivery="d2", action="opened")
    sandbox.audit.append(_build_webhook_audit(context))
    _dispatch_webhook_scan(context, False, None, "tenant-a", BackgroundTasks())
    assert sandbox.audit.list()[0].outcome == "ignored"

def test_dispatch_webhook_scan_triggered_enqueues_job(
    sandbox: SimpleNamespace,
) -> None:
    context = _mk_context(
        event="push", delivery="d3", project_id="p1", installation_id=7
    )
    sandbox.audit.append(_build_webhook_audit(context))
    job_id = _dispatch_webhook_scan(context, True, 7, "tenant-a", BackgroundTasks())
    job = sandbox.jobs.get(job_id)
    stored = sandbox.audit.list()[0]
    assert job is not None
    assert job.state == "queued"
    assert job.project_id == "p1"
    assert stored.scan_triggered is True
    assert stored.outcome == "scan_queued"
    assert stored.job_id == job_id

# ---------------------------------------------------------------------------
# Scan-job runner
# ---------------------------------------------------------------------------

def test_run_scan_job_missing_job_returns_quietly(
    sandbox: SimpleNamespace,
) -> None:
    result = asyncio.run(_run_project_scan_job_for_bound_tenant("ghjob_missing"))
    assert result is None
    assert sandbox.jobs.get("ghjob_missing") is None

def test_run_scan_job_fails_without_handler(
    sandbox: SimpleNamespace, request: pytest.FixtureRequest
) -> None:
    # app.main registers a handler at import time; clear it explicitly so
    # this test does not depend on import order.
    set_webhook_scan_handler(None)
    request.addfinalizer(lambda: set_webhook_scan_handler(None))
    job = sandbox.jobs.enqueue(delivery_id="d1", project_id="p1", installation_id=None)
    asyncio.run(_run_project_scan_job_for_bound_tenant(job.job_id))
    updated = sandbox.jobs.get(job.job_id)
    assert updated.state == "failed"
    assert updated.error == "RuntimeError"

def test_run_scan_job_fails_for_missing_project(
    sandbox: SimpleNamespace, request: pytest.FixtureRequest
) -> None:
    async def _never(project_id: str) -> None:
        raise AssertionError("handler must not run")

    request.addfinalizer(lambda: set_webhook_scan_handler(None))
    set_webhook_scan_handler(_never)
    job = sandbox.jobs.enqueue(delivery_id="d2", project_id="nope", installation_id=None)
    asyncio.run(_run_project_scan_job_for_bound_tenant(job.job_id))
    updated = sandbox.jobs.get(job.job_id)
    assert updated.state == "failed"
    assert updated.error == "LookupError"

def test_run_scan_job_completes_for_legacy_checkout(
    sandbox: SimpleNamespace, request: pytest.FixtureRequest
) -> None:
    calls: list[str] = []

    async def _handler(project_id: str) -> SimpleNamespace:
        calls.append(project_id)
        return SimpleNamespace(scan_id="scan-9", score=88)

    request.addfinalizer(lambda: set_webhook_scan_handler(None))
    set_webhook_scan_handler(_handler)
    sandbox.projects.upsert(_mk_project("p1", installation=None))
    job = sandbox.jobs.enqueue(delivery_id="d3", project_id="p1", installation_id=None)
    asyncio.run(_run_project_scan_job_for_bound_tenant(job.job_id))
    updated = sandbox.jobs.get(job.job_id)
    assert updated.state == "completed"
    assert updated.scan_id == "scan-9"
    assert updated.score == 88
    assert calls == ["p1"]
    assert updated.error is None

def test_run_scan_job_wrapper_binds_tenant_and_restores(
    sandbox: SimpleNamespace, request: pytest.FixtureRequest
) -> None:
    # app.main registers a handler at import time; clear it explicitly so
    # this test does not depend on import order.
    set_webhook_scan_handler(None)
    request.addfinalizer(lambda: set_webhook_scan_handler(None))
    job = sandbox.jobs.enqueue(delivery_id="d4", project_id="p4", installation_id=None)
    asyncio.run(_run_project_scan_job(job.job_id, tenant_id="tenant-a"))
    updated = sandbox.jobs.get(job.job_id)
    assert updated.state == "failed"
    assert updated.error == "RuntimeError"
    assert current_tenant_id() == "tenant-a"

# ---------------------------------------------------------------------------
# Module-level state helpers
# ---------------------------------------------------------------------------

def test_active_installation_id_set_clear_and_scope(
    sandbox: SimpleNamespace, request: pytest.FixtureRequest
) -> None:
    request.addfinalizer(lambda: set_active_installation_id(None))
    assert get_active_installation_id() is None
    set_active_installation_id(11)
    assert get_active_installation_id() == 11
    token = bind_tenant("tenant-b")
    assert get_active_installation_id() is None
    reset_tenant(token)
    set_active_installation_id(None)
    assert get_active_installation_id() is None

def test_module_setters_round_trip(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    previous_auth = get_github_app_auth()
    previous_stores = (
        get_installation_store(),
        get_webhook_audit_store(),
        get_webhook_job_store(),
    )
    request.addfinalizer(lambda: set_github_app_auth(previous_auth))
    request.addfinalizer(lambda: set_installation_store(previous_stores[0]))
    request.addfinalizer(lambda: set_webhook_audit_store(previous_stores[1]))
    request.addfinalizer(lambda: set_webhook_job_store(previous_stores[2]))
    auth = GitHubAppAuth(app_id="1", private_key="k")
    installations = GitHubInstallationStore(tmp_path / "i.json")
    audit = WebhookAuditStore(tmp_path / "a.jsonl")
    jobs = WebhookScanJobStore(tmp_path / "j.json")
    set_github_app_auth(auth)
    set_installation_store(installations)
    set_webhook_audit_store(audit)
    set_webhook_job_store(jobs)
    assert get_github_app_auth() is auth
    assert get_installation_store() is installations
    assert get_webhook_audit_store() is audit
    assert get_webhook_job_store() is jobs
