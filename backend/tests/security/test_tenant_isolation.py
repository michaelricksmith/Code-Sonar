"""Cross-tenant API and persistence isolation regressions."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ask_sonar.runtime import set_scan_provider
from app.github_app import (
    GitHubInstallation,
    GitHubInstallationStore,
    WebhookAuditStore,
    WebhookScanJobStore,
    get_installation_store,
    get_webhook_audit_store,
    get_webhook_job_store,
    set_installation_store,
    set_webhook_audit_store,
    set_webhook_job_store,
    set_webhook_scan_handler,
)
from app.history import InMemoryHistoryStore, ScanRecord
from app.main import app, get_history_store, scan_project, set_history_store
from app.projects import ProjectRecord, ProjectStore, get_project_store, set_project_store
from app.security.tenant import bind_tenant, current_tenant_id, reset_tenant


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _scan(tenant_id: str, scan_id: str) -> ScanRecord:
    return ScanRecord(
        scan_id=scan_id,
        tenant_id=tenant_id,
        repository_id="same-repository",
        repository_path="repo",
        scanned_at="2026-09-02T00:00:00+00:00",
        schema_version="1.0",
        score=700,
        grade="B",
        total_debt_points=1,
        finding_count=0,
        category_scores={},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={},
        findings=[],
    )


@pytest.fixture
def tenant_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    monkeypatch.setenv(
        "CODESONAR_API_TENANT_TOKENS",
        json.dumps({"tenant-a": "token-a", "tenant-b": "token-b"}),
    )
    return TestClient(app)


def test_history_and_ask_sonar_hide_other_tenant_scan(tenant_client: TestClient) -> None:
    previous = get_history_store()
    store = InMemoryHistoryStore()
    store._records.extend([_scan("tenant-a", "scan-a"), _scan("tenant-b", "scan-b")])
    set_history_store(store)
    set_scan_provider(store.get)
    try:
        own = tenant_client.get("/api/history/scan-a", headers=_headers("token-a"))
        denied = tenant_client.get("/api/history/scan-a", headers=_headers("token-b"))
        ask_denied = tenant_client.get(
            "/api/ask-sonar/context/scan-a", headers=_headers("token-b")
        )
        plan_denied = tenant_client.get(
            "/api/ask-sonar/remediation-plan/scan-a/finding-a",
            headers=_headers("token-b"),
        )
        listed = tenant_client.get("/api/history/list", headers=_headers("token-b"))
        assert own.status_code == 200
        assert denied.status_code == 404
        assert ask_denied.status_code == 404
        assert plan_denied.status_code == 404
        assert [item["scan_id"] for item in listed.json()["scans"]] == ["scan-b"]
    finally:
        set_scan_provider(None)
        set_history_store(previous)


def test_projects_and_installations_are_tenant_scoped(
    tenant_client: TestClient, tmp_path: Path
) -> None:
    previous_projects = get_project_store()
    from app.github_app import get_installation_store

    previous_installations = get_installation_store()
    projects = ProjectStore(tmp_path / "projects.json")
    installations = GitHubInstallationStore(tmp_path / "installations.json")
    token = bind_tenant("tenant-a")
    try:
        projects.upsert(
            ProjectRecord(
                project_id="project-a",
                provider="github",
                owner="acme",
                name="secret",
                default_branch="main",
                connected_at="now",
                local_checkout_path=str(tmp_path),
            )
        )
        installations.upsert(
            GitHubInstallation(1, "acme", "Organization", "now", "now")
        )
    finally:
        reset_tenant(token)
    set_project_store(projects)
    set_installation_store(installations)
    try:
        assert tenant_client.get(
            "/api/projects/project-a", headers=_headers("token-a")
        ).status_code == 200
        assert tenant_client.get(
            "/api/projects/project-a", headers=_headers("token-b")
        ).status_code == 404
        assert tenant_client.get(
            "/api/projects/project-a/dashboard", headers=_headers("token-b")
        ).status_code == 404
        assert tenant_client.get(
            "/api/github-app/installations", headers=_headers("token-a")
        ).json()["count"] == 1
        assert tenant_client.get(
            "/api/github-app/installations", headers=_headers("token-b")
        ).json()["count"] == 0
        assert tenant_client.post(
            "/api/github-app/installations/1/activate", headers=_headers("token-b")
        ).status_code == 404
    finally:
        set_project_store(previous_projects)
        set_installation_store(previous_installations)


def test_caller_tenant_header_cannot_override_token_identity(
    tenant_client: TestClient,
) -> None:
    response = tenant_client.get(
        "/api/history/list",
        headers={**_headers("token-a"), "X-Code-Sonar-Tenant": "tenant-b"},
    )
    assert response.status_code == 200


def test_verified_webhook_resolves_tenant_from_stored_installation_only(
    tenant_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)
    previous_projects = get_project_store()
    previous_installations = get_installation_store()
    previous_audit = get_webhook_audit_store()
    previous_jobs = get_webhook_job_store()
    projects = ProjectStore(tmp_path / "projects.json")
    installations = GitHubInstallationStore(tmp_path / "installations.json")

    for tenant_id, installation_id, project_id in (
        ("tenant-a", 101, "project-a"),
        ("tenant-b", 202, "project-b"),
    ):
        tenant_token = bind_tenant(tenant_id)
        try:
            projects.upsert(
                ProjectRecord(
                    project_id=project_id,
                    provider="github",
                    owner="acme",
                    name="shared-name",
                    default_branch="main",
                    connected_at="now",
                    local_checkout_path=str(tmp_path / tenant_id),
                    provider_installation_id=None,
                )
            )
            installations.upsert(
                GitHubInstallation(
                    installation_id,
                    tenant_id,
                    "Organization",
                    "now",
                    "now",
                )
            )
        finally:
            reset_tenant(tenant_token)

    set_project_store(projects)
    set_installation_store(installations)
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
    set_webhook_job_store(WebhookScanJobStore(tmp_path / "jobs.json"))
    calls: list[tuple[str, str]] = []

    async def fake_scan(project_id: str) -> object:
        calls.append((current_tenant_id(), project_id))
        return SimpleNamespace(scan_id="scan-b", score=710)

    set_webhook_scan_handler(fake_scan)
    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "repository": {"full_name": "acme/shared-name"},
            "installation": {"id": 202},
            "tenant_id": "tenant-a",
        }
    ).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        response = tenant_client.post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "tenant-webhook",
                "X-Hub-Signature-256": signature,
                "X-Code-Sonar-Tenant": "tenant-a",
            },
        )
        assert response.status_code == 200
        assert response.json()["project_id"] == "project-b"
        assert calls == [("tenant-b", "project-b")]
        job_id = response.json()["job_id"]
        assert tenant_client.get(
            f"/api/github-app/webhook-jobs/{job_id}", headers=_headers("token-a")
        ).status_code == 404
        own_job = tenant_client.get(
            f"/api/github-app/webhook-jobs/{job_id}", headers=_headers("token-b")
        )
        assert own_job.status_code == 200
        assert "tenant_id" not in own_job.json()["job"]
    finally:
        set_webhook_scan_handler(scan_project)
        set_project_store(previous_projects)
        set_installation_store(previous_installations)
        set_webhook_audit_store(previous_audit)
        set_webhook_job_store(previous_jobs)
