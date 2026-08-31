"""Security and lifecycle coverage for the GitHub App integration."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.github_app import (
    GitHubAppRuntime,
    GitHubAppSettings,
    GitHubInstallationRecord,
    GitHubInstallationStore,
    GitHubWebhookDeliveryStore,
    GitHubWebhookJobStore,
    get_github_app_runtime,
    get_webhook_delivery_store,
    get_webhook_job_store,
    get_webhook_processor,
    set_github_app_runtime,
    set_webhook_delivery_store,
    set_webhook_job_store,
    set_webhook_processor,
)
from app.main import app
from app.projects import ProjectRecord, ProjectStore, get_project_store, set_project_store


def _settings(*, private_key: str = "unused") -> GitHubAppSettings:
    return GitHubAppSettings(
        app_id="12345",
        slug="code-sonar-test",
        private_key=private_key,
        webhook_secret="webhook-secret",
        state_secret="state-secret",
    )


def _private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def _signature(body: bytes) -> str:
    digest = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_install_state_is_signed_and_tamper_rejected(tmp_path: Path) -> None:
    runtime = GitHubAppRuntime(
        settings=_settings(),
        installations=GitHubInstallationStore(tmp_path / "installations.json"),
    )

    state = runtime.issue_install_state()
    assert runtime.verify_install_state(state) is True
    assert runtime.verify_install_state(state + "tampered") is False
    assert "state=" in runtime.install_url()


def test_callback_persists_installation_identity_but_not_token(tmp_path: Path) -> None:
    private_key = _private_key_pem()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/app/installations/42"
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "id": 42,
                "repository_selection": "selected",
                "account": {"login": "octo", "type": "Organization"},
            },
        )

    previous_runtime = get_github_app_runtime()
    store = GitHubInstallationStore(tmp_path / "installations.json")
    runtime = GitHubAppRuntime(
        settings=_settings(private_key=private_key),
        installations=store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    set_github_app_runtime(runtime)
    client = TestClient(app)
    try:
        state = runtime.issue_install_state()
        response = client.get(
            "/api/github-app/callback",
            params={"installation_id": 42, "setup_action": "install", "state": state},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["connected"] is True
        assert payload["installation"]["installation_id"] == 42
        assert payload["installation_token_persisted"] is False
        assert payload["installation_token_exposed"] is False
        persisted = (tmp_path / "installations.json").read_text(encoding="utf-8")
        assert "token" not in persisted.lower()
        assert "private_key" not in persisted.lower()
        assert seen
    finally:
        set_github_app_runtime(previous_runtime)


def test_webhook_rejects_invalid_signature(tmp_path: Path) -> None:
    previous_runtime = get_github_app_runtime()
    runtime = GitHubAppRuntime(
        settings=_settings(),
        installations=GitHubInstallationStore(tmp_path / "installations.json"),
    )
    set_github_app_runtime(runtime)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/github-app/webhook",
            content=b"{}",
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-1",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        assert response.status_code == 401
    finally:
        set_github_app_runtime(previous_runtime)


def test_signed_default_branch_push_queues_once_without_exposing_secrets(
    tmp_path: Path,
) -> None:
    previous_runtime = get_github_app_runtime()
    previous_projects = get_project_store()
    previous_jobs = get_webhook_job_store()
    previous_deliveries = get_webhook_delivery_store()
    previous_processor = get_webhook_processor()

    installation_store = GitHubInstallationStore(tmp_path / "installations.json")
    installation_store.upsert(
        GitHubInstallationRecord(
            installation_id=42,
            account_login="octo",
            account_type="Organization",
            repository_selection="selected",
            installed_at="2026-08-30T00:00:00+00:00",
            updated_at="2026-08-30T00:00:00+00:00",
        )
    )
    runtime = GitHubAppRuntime(settings=_settings(), installations=installation_store)
    project_store = ProjectStore(tmp_path / "projects.json")
    project_store.upsert(
        ProjectRecord(
            project_id="proj_test",
            provider="github",
            owner="octo",
            name="example",
            default_branch="main",
            connected_at="2026-08-30T00:00:00+00:00",
            local_checkout_path=str(tmp_path / "managed" / "123"),
            provider_installation_id=42,
        )
    )
    job_store = GitHubWebhookJobStore(tmp_path / "jobs.json")
    delivery_store = GitHubWebhookDeliveryStore(tmp_path / "deliveries.json")
    processed: list[str] = []

    set_github_app_runtime(runtime)
    set_project_store(project_store)
    set_webhook_job_store(job_store)
    set_webhook_delivery_store(delivery_store)
    set_webhook_processor(processed.append)
    client = TestClient(app)

    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "repository": {"full_name": "octo/example"},
            "installation": {"id": 42},
        }
    ).encode("utf-8")
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-42",
        "X-Hub-Signature-256": _signature(body),
        "Content-Type": "application/json",
    }
    try:
        first = client.post("/api/github-app/webhook", content=body, headers=headers)
        assert first.status_code == 202
        payload = first.json()
        assert payload["accepted"] is True
        assert payload["queued"] is True
        assert payload["project_id"] == "proj_test"
        assert payload["token_persisted"] is False
        assert payload["token_exposed"] is False
        assert processed == [payload["job_id"]]

        second = client.post("/api/github-app/webhook", content=body, headers=headers)
        assert second.status_code == 202
        assert second.json() == {"accepted": True, "duplicate": True, "queued": False}
        assert processed == [payload["job_id"]]

        delivery = delivery_store.list()[0]
        assert delivery.outcome == "scan_queued"
        assert delivery.job_id == payload["job_id"]
        public_text = str(payload)
        assert str(tmp_path) not in public_text
        assert "webhook-secret" not in public_text
    finally:
        set_github_app_runtime(previous_runtime)
        set_project_store(previous_projects)
        set_webhook_job_store(previous_jobs)
        set_webhook_delivery_store(previous_deliveries)
        set_webhook_processor(previous_processor)


def test_non_default_branch_push_is_ignored(tmp_path: Path) -> None:
    previous_runtime = get_github_app_runtime()
    previous_projects = get_project_store()
    previous_deliveries = get_webhook_delivery_store()
    runtime = GitHubAppRuntime(
        settings=_settings(),
        installations=GitHubInstallationStore(tmp_path / "installations.json"),
    )
    project_store = ProjectStore(tmp_path / "projects.json")
    project_store.upsert(
        ProjectRecord(
            project_id="proj_test",
            provider="github",
            owner="octo",
            name="example",
            default_branch="main",
            connected_at="2026-08-30T00:00:00+00:00",
            local_checkout_path=str(tmp_path / "managed" / "123"),
            provider_installation_id=42,
        )
    )
    delivery_store = GitHubWebhookDeliveryStore(tmp_path / "deliveries.json")
    set_github_app_runtime(runtime)
    set_project_store(project_store)
    set_webhook_delivery_store(delivery_store)
    client = TestClient(app)
    body = json.dumps(
        {
            "ref": "refs/heads/feature/test",
            "repository": {"full_name": "octo/example"},
            "installation": {"id": 42},
        }
    ).encode("utf-8")
    try:
        response = client.post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-feature",
                "X-Hub-Signature-256": _signature(body),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202
        assert response.json()["outcome"] == "ignored_non_default_branch"
    finally:
        set_github_app_runtime(previous_runtime)
        set_project_store(previous_projects)
        set_webhook_delivery_store(previous_deliveries)
