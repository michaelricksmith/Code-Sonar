"""Security and lifecycle tests for GitHub App webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.github_app import (
    GitHubInstallationStore,
    WebhookAuditStore,
    get_installation_store,
    get_webhook_audit_store,
    set_installation_store,
    set_webhook_audit_store,
    set_webhook_scan_handler,
)
from app.main import app, scan_project
from app.projects import ProjectRecord, ProjectStore, get_project_store, set_project_store


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_rejects_invalid_signature(monkeypatch: object) -> None:
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "webhook-secret")  # type: ignore[attr-defined]
    response = TestClient(app).post(
        "/api/github-app/webhook",
        content=b"{}",
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "delivery-invalid",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )
    assert response.status_code == 401


def test_installation_event_is_persisted_without_token(tmp_path: Path, monkeypatch: object) -> None:
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)  # type: ignore[attr-defined]
    previous = get_installation_store()
    set_installation_store(GitHubInstallationStore(tmp_path / "installations.json"))
    body = json.dumps(
        {
            "action": "created",
            "installation": {
                "id": 777,
                "account": {"login": "octo", "type": "Organization"},
            },
        }
    ).encode()
    try:
        response = TestClient(app).post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "installation",
                "X-GitHub-Delivery": "delivery-install",
                "X-Hub-Signature-256": _signature(secret, body),
            },
        )
        assert response.status_code == 200
        installations = get_installation_store().list()
        assert installations[0].installation_id == 777
        assert "token" not in (tmp_path / "installations.json").read_text(encoding="utf-8").lower()
    finally:
        set_installation_store(previous)


def test_default_branch_push_triggers_one_project_scan_and_deduplicates(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)  # type: ignore[attr-defined]
    previous_projects = get_project_store()
    previous_audit = get_webhook_audit_store()
    project_store = ProjectStore(tmp_path / "projects.json")
    project = ProjectRecord(
        project_id="proj_test",
        provider="github",
        owner="octo",
        name="example",
        default_branch="main",
        connected_at="2026-08-30T00:00:00+00:00",
        local_checkout_path=str(tmp_path / "checkout"),
        provider_repository_id=123,
        provider_installation_id=None,
    )
    project_store.upsert(project)
    set_project_store(project_store)
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
    calls: list[str] = []

    async def fake_scan(project_id: str) -> None:
        calls.append(project_id)

    set_webhook_scan_handler(fake_scan)
    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "repository": {"id": 123, "full_name": "octo/example"},
        }
    ).encode()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-push",
        "X-Hub-Signature-256": _signature(secret, body),
    }
    try:
        client = TestClient(app)
        first = client.post("/api/github-app/webhook", content=body, headers=headers)
        second = client.post("/api/github-app/webhook", content=body, headers=headers)

        assert first.status_code == 200
        assert first.json()["scan_triggered"] is True
        assert first.json()["project_id"] == "proj_test"
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert second.json()["scan_triggered"] is False
        assert calls == ["proj_test"]
    finally:
        set_webhook_scan_handler(scan_project)
        set_webhook_audit_store(previous_audit)
        set_project_store(previous_projects)


def test_non_default_branch_push_does_not_trigger_scan(tmp_path: Path, monkeypatch: object) -> None:
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)  # type: ignore[attr-defined]
    previous_projects = get_project_store()
    previous_audit = get_webhook_audit_store()
    project_store = ProjectStore(tmp_path / "projects.json")
    project_store.upsert(
        ProjectRecord(
            project_id="proj_test",
            provider="github",
            owner="octo",
            name="example",
            default_branch="main",
            connected_at="2026-08-30T00:00:00+00:00",
            local_checkout_path=str(tmp_path / "checkout"),
            provider_repository_id=123,
        )
    )
    set_project_store(project_store)
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
    calls: list[str] = []

    async def fake_scan(project_id: str) -> None:
        calls.append(project_id)

    set_webhook_scan_handler(fake_scan)
    body = json.dumps(
        {
            "ref": "refs/heads/feature/example",
            "repository": {"id": 123, "full_name": "octo/example"},
        }
    ).encode()
    try:
        response = TestClient(app).post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-feature",
                "X-Hub-Signature-256": _signature(secret, body),
            },
        )
        assert response.status_code == 200
        assert response.json()["scan_triggered"] is False
        assert calls == []
    finally:
        set_webhook_scan_handler(scan_project)
        set_webhook_audit_store(previous_audit)
        set_project_store(previous_projects)
