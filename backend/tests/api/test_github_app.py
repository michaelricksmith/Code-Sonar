"""Unit tests for ``app.github_app`` — installation, audit, and scan-job stores.

Companion files: ``tests/api/test_github_app_auth.py`` covers
``GitHubAppAuth``, install-state signing, and webhook signature
verification; ``tests/api/test_github_app_dispatch.py`` covers the
webhook payload/context/trigger helpers, the scan-job runner, and the
module-level setter/getter surface;
``tests/api/test_github_app_webhooks.py`` covers the ``/webhook`` route
end-to-end. This module covers the installation store (including
tenant scoping and rebinding), the webhook audit store (claim,
update, tenant scoping), and the scan-job store (deterministic
enqueue, claim transitions, updates).
Edge cases (``None``/empty inputs, duplicate claims, unknown tenants)
and error paths are included throughout.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.github_app import (
    GitHubInstallation,
    GitHubInstallationStore,
    WebhookAuditRecord,
    WebhookAuditStore,
    WebhookScanJobStore,
    get_installation_store,
    get_webhook_audit_store,
    get_webhook_job_store,
    set_installation_store,
    set_webhook_audit_store,
    set_webhook_job_store,
)
from app.projects import (
    ProjectStore,
    get_project_store,
    set_project_store,
)
from app.security.tenant import bind_tenant, reset_tenant

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
def _mk_audit(delivery_id: str = "d1", tenant: str = "tenant-a") -> WebhookAuditRecord:
    return WebhookAuditRecord(
        delivery_id=delivery_id,
        event="push",
        action="created",
        repository_full_name="octo/example",
        installation_id=7,
        project_id="p1",
        accepted=True,
        scan_triggered=False,
        received_at="2026-09-28T00:00:00+00:00",
        tenant_id=tenant,
    )
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

# ---------------------------------------------------------------------------
# GitHubInstallationStore
# ---------------------------------------------------------------------------

def test_installation_to_public_dict_hides_tenant() -> None:
    public = _mk_installation().to_public_dict()
    assert "tenant_id" not in public
    assert public["installation_id"] == 7
    assert public["account_login"] == "octo"

def test_installation_store_round_trip(sandbox: SimpleNamespace) -> None:
    sandbox.installations.upsert(_mk_installation(7))
    sandbox.installations.upsert(_mk_installation(8, login="other"))
    fetched = sandbox.installations.get(7)
    assert fetched is not None
    assert fetched.account_login == "octo"
    assert len(sandbox.installations.list()) == 2
    assert (sandbox.tmp / "installations.json").exists()

def test_installation_store_upsert_rebinds_foreign_tenant(
    sandbox: SimpleNamespace,
) -> None:
    record = sandbox.installations.upsert(_mk_installation(7, tenant="other-tenant"))
    assert record.tenant_id == "tenant-a"
    assert sandbox.installations.get(7) is not None

def test_installation_store_scopes_records_by_tenant(
    sandbox: SimpleNamespace,
) -> None:
    sandbox.installations.upsert(_mk_installation(7))
    token = bind_tenant("tenant-b")
    sandbox.installations.upsert(_mk_installation(7, login="bee"))
    reset_tenant(token)
    assert len(sandbox.installations.list()) == 1
    assert sandbox.installations.get(7).account_login == "octo"

def test_installation_store_remove(sandbox: SimpleNamespace) -> None:
    sandbox.installations.upsert(_mk_installation(7))
    sandbox.installations.upsert(_mk_installation(8))
    sandbox.installations.remove(7)
    assert sandbox.installations.get(7) is None
    assert len(sandbox.installations.list()) == 1

def test_tenant_for_installation_resolves_unique_owner(
    sandbox: SimpleNamespace,
) -> None:
    assert sandbox.installations.tenant_for_installation(7) is None
    sandbox.installations.upsert(_mk_installation(7))
    assert sandbox.installations.tenant_for_installation(7) == "tenant-a"

def test_tenant_for_installation_rejects_ambiguous_owner(
    sandbox: SimpleNamespace,
) -> None:
    sandbox.installations.upsert(_mk_installation(7))
    token = bind_tenant("tenant-b")
    sandbox.installations.upsert(_mk_installation(7, login="bee"))
    reset_tenant(token)
    assert sandbox.installations.tenant_for_installation(7) is None

# ---------------------------------------------------------------------------
# WebhookAuditStore
# ---------------------------------------------------------------------------

def test_audit_store_claim_append_and_list(sandbox: SimpleNamespace) -> None:
    assert sandbox.audit.claim(_mk_audit("d1")) is True
    sandbox.audit.append(_mk_audit("d2"))
    sandbox.audit.append(_mk_audit("d3"))
    assert sandbox.audit.has_delivery("d1") is True
    assert sandbox.audit.has_delivery("nope") is False
    recent = sandbox.audit.list(limit=2)
    assert [record.delivery_id for record in recent] == ["d2", "d3"]

def test_audit_store_claim_rejects_duplicate(sandbox: SimpleNamespace) -> None:
    assert sandbox.audit.claim(_mk_audit("d1")) is True
    assert sandbox.audit.claim(_mk_audit("d1")) is False
    assert len(sandbox.audit.list()) == 1

def test_audit_store_update_and_public_dict(sandbox: SimpleNamespace) -> None:
    sandbox.audit.claim(_mk_audit("d1"))
    updated = sandbox.audit.update("d1", scan_triggered=True, outcome="scan_queued")
    assert updated.scan_triggered is True
    assert updated.outcome == "scan_queued"
    public = updated.to_public_dict()
    assert "tenant_id" not in public
    assert public["delivery_id"] == "d1"

def test_audit_store_update_missing_raises(sandbox: SimpleNamespace) -> None:
    with pytest.raises(LookupError):
        sandbox.audit.update("missing", outcome="ignored")

def test_audit_store_claim_scopes_by_tenant(sandbox: SimpleNamespace) -> None:
    sandbox.audit.claim(_mk_audit("d1"))
    token = bind_tenant("tenant-b")
    claimed = sandbox.audit.claim(_mk_audit("d1"))
    reset_tenant(token)
    assert claimed is True
    assert sandbox.audit.has_delivery("d1") is True

# ---------------------------------------------------------------------------
# WebhookScanJobStore
# ---------------------------------------------------------------------------

def test_job_store_enqueue_is_deterministic(sandbox: SimpleNamespace) -> None:
    first = sandbox.jobs.enqueue(delivery_id="d1", project_id="p1", installation_id=7)
    second = sandbox.jobs.enqueue(delivery_id="d1", project_id="p1", installation_id=7)
    assert first.job_id == second.job_id
    assert first.job_id.startswith("ghjob_")
    assert first.state == "queued"
    assert len(first.job_id) == len("ghjob_") + 24
    fetched = sandbox.jobs.get(first.job_id)
    assert fetched is not None
    assert fetched.project_id == "p1"

def test_job_store_claim_queued_transitions(sandbox: SimpleNamespace) -> None:
    job = sandbox.jobs.enqueue(delivery_id="d1", project_id="p1", installation_id=None)
    assert sandbox.jobs.claim_queued(job.job_id) is True
    assert sandbox.jobs.get(job.job_id).state == "running"
    assert sandbox.jobs.claim_queued(job.job_id) is False
    assert sandbox.jobs.claim_queued("ghjob_missing") is False

def test_job_store_update_and_public_dict(sandbox: SimpleNamespace) -> None:
    job = sandbox.jobs.enqueue(delivery_id="d1", project_id="p1", installation_id=None)
    updated = sandbox.jobs.update(job.job_id, state="completed", score=90)
    assert updated.state == "completed"
    assert updated.score == 90
    public = updated.to_public_dict()
    assert "tenant_id" not in public

def test_job_store_update_missing_raises(sandbox: SimpleNamespace) -> None:
    with pytest.raises(LookupError):
        sandbox.jobs.update("ghjob_missing", state="failed")
