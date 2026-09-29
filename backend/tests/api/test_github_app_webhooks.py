"""Security and lifecycle tests for GitHub App webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.github_app import (
    GitHubAppAuth,
    GitHubInstallation,
    GitHubInstallationStore,
    WebhookAuditStore,
    WebhookScanJobStore,
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
from app.github_integration import GitHubIntegration, get_github_integration, set_github_integration
from app.main import app, scan_project
from app.projects import ProjectRecord, ProjectStore, get_project_store, set_project_store


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class FakeGitHubAppAuth:
    configured = True

    def __init__(self) -> None:
        self.token_requests: list[int] = []
        self.detail_requests: list[int] = []

    def installation_details(self, installation_id: int) -> dict[str, object]:
        self.detail_requests.append(installation_id)
        return {
            "id": installation_id,
            "repository_selection": "selected",
            "account": {"login": "octo", "type": "Organization"},
        }

    def installation_token(self, installation_id: int) -> str:
        self.token_requests.append(installation_id)
        return "ephemeral-installation-token"


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


def _setup_install_flow(
    tmp_path: Path, monkeypatch: object
) -> tuple[TestClient, FakeGitHubAppAuth, tuple[GitHubAppAuth, GitHubInstallationStore, int | None]]:
    """Prepare the GitHub App install/callback environment.

    Returns the test client, the fake auth backend, and the previously active
    globals so a test can restore them in a ``finally`` block.
    """
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_SLUG", "code-sonar-test")  # type: ignore[attr-defined]
    monkeypatch.setenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "state-secret")  # type: ignore[attr-defined]
    previous = (get_github_app_auth(), get_installation_store(), get_active_installation_id())
    fake_auth = FakeGitHubAppAuth()
    set_github_app_auth(fake_auth)  # type: ignore[arg-type]
    set_installation_store(GitHubInstallationStore(tmp_path / "installations.json"))
    set_active_installation_id(None)
    return TestClient(app), fake_auth, previous


def _restore_install_flow(
    previous: tuple[GitHubAppAuth, GitHubInstallationStore, int | None],
) -> None:
    """Restore the globals replaced by :func:`_setup_install_flow`."""
    previous_auth, previous_store, previous_active = previous
    set_github_app_auth(previous_auth)
    set_installation_store(previous_store)
    set_active_installation_id(previous_active)


def _install_state(client: TestClient) -> str:
    """Fetch a fresh signed install state from the install-url endpoint."""
    install = client.get("/api/github-app/install-url")
    assert install.status_code == 200
    return parse_qs(urlparse(install.json()["install_url"]).query)["state"][0]


def test_install_url_uses_signed_state(tmp_path: Path, monkeypatch: object) -> None:
    client, _, previous = _setup_install_flow(tmp_path, monkeypatch)
    try:
        install = client.get("/api/github-app/install-url")
        assert install.status_code == 200
        install_payload = install.json()
        assert install_payload["state_signed"] is True
    finally:
        _restore_install_flow(previous)


def test_callback_persists_installation_identity_only(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    client, _, previous = _setup_install_flow(tmp_path, monkeypatch)
    try:
        state = _install_state(client)
        callback = client.get(
            "/api/github-app/callback",
            params={"installation_id": 42, "setup_action": "install", "state": state},
        )
        assert callback.status_code == 200
        payload = callback.json()
        assert payload["connected"] is True
        assert payload["installation"]["installation_id"] == 42
        assert payload["token_persisted"] is False
        assert payload["token_exposed"] is False
    finally:
        _restore_install_flow(previous)


def test_callback_records_installation_side_effects(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    client, fake_auth, previous = _setup_install_flow(tmp_path, monkeypatch)
    try:
        state = _install_state(client)
        callback = client.get(
            "/api/github-app/callback",
            params={"installation_id": 42, "setup_action": "install", "state": state},
        )
        assert callback.status_code == 200
        assert fake_auth.detail_requests == [42]
        assert fake_auth.token_requests == []
        assert get_active_installation_id() == 42
    finally:
        _restore_install_flow(previous)


def test_callback_persisted_installation_contains_no_secrets(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    client, _, previous = _setup_install_flow(tmp_path, monkeypatch)
    try:
        state = _install_state(client)
        callback = client.get(
            "/api/github-app/callback",
            params={"installation_id": 42, "setup_action": "install", "state": state},
        )
        assert callback.status_code == 200
        persisted = (tmp_path / "installations.json").read_text(encoding="utf-8")
        assert "ephemeral-installation-token" not in persisted
        assert "state-secret" not in persisted
    finally:
        _restore_install_flow(previous)


def test_callback_rejects_tampered_state(tmp_path: Path, monkeypatch: object) -> None:
    client, _, previous = _setup_install_flow(tmp_path, monkeypatch)
    try:
        state = _install_state(client)
        tampered = client.get(
            "/api/github-app/callback",
            params={
                "installation_id": 42,
                "setup_action": "install",
                "state": state + "tampered",
            },
        )
        assert tampered.status_code == 400
    finally:
        _restore_install_flow(previous)


def test_activation_verifies_ephemeral_token_without_mutating_global_integration(
    tmp_path: Path,
) -> None:
    previous_auth = get_github_app_auth()
    previous_store = get_installation_store()
    previous_integration = get_github_integration()
    previous_active = get_active_installation_id()
    fake_auth = FakeGitHubAppAuth()
    store = GitHubInstallationStore(tmp_path / "installations.json")
    store.upsert(
        GitHubInstallation(
            installation_id=77,
            account_login="octo",
            account_type="Organization",
            installed_at="2026-08-30T00:00:00+00:00",
            updated_at="2026-08-30T00:00:00+00:00",
        )
    )
    static_integration = GitHubIntegration(token="static-fallback", auth_mode="oauth")
    set_github_app_auth(fake_auth)  # type: ignore[arg-type]
    set_installation_store(store)
    set_github_integration(static_integration)
    set_active_installation_id(None)
    try:
        response = TestClient(app).post("/api/github-app/installations/77/activate")
        assert response.status_code == 200
        assert response.json()["token_persisted"] is False
        assert response.json()["token_exposed"] is False
        assert fake_auth.token_requests == [77]
        assert get_active_installation_id() == 77
        assert get_github_integration() is static_integration
        assert get_github_integration().token == "static-fallback"
    finally:
        set_github_app_auth(previous_auth)
        set_installation_store(previous_store)
        set_github_integration(previous_integration)
        set_active_installation_id(previous_active)


def test_unknown_installation_event_does_not_claim_a_tenant(
    tmp_path: Path, monkeypatch: object
) -> None:
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)  # type: ignore[attr-defined]
    previous = get_installation_store()
    previous_audit = get_webhook_audit_store()
    set_installation_store(GitHubInstallationStore(tmp_path / "installations.json"))
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
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
        assert response.json()["scan_triggered"] is False
        assert get_installation_store().list() == []
        assert not (tmp_path / "installations.json").exists()
    finally:
        set_installation_store(previous)
        set_webhook_audit_store(previous_audit)


def _setup_default_branch_push(
    tmp_path: Path, monkeypatch: object
) -> tuple[
    TestClient,
    bytes,
    dict[str, str],
    list[str],
    tuple[ProjectStore, GitHubInstallationStore, WebhookAuditStore, WebhookScanJobStore],
]:
    """Prepare stores and a fake scan handler for a default-branch push webhook.

    Returns the test client, the signed request body and headers, the recorded
    scan calls, and the previously active globals so a test can restore them in
    a ``finally`` block.
    """
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)  # type: ignore[attr-defined]
    previous = (
        get_project_store(),
        get_installation_store(),
        get_webhook_audit_store(),
        get_webhook_job_store(),
    )
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
    installation_store = GitHubInstallationStore(tmp_path / "installations.json")
    installation_store.upsert(
        GitHubInstallation(900, "octo", "Organization", "now", "now")
    )
    set_installation_store(installation_store)
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
    set_webhook_job_store(WebhookScanJobStore(tmp_path / "jobs.json"))
    calls: list[str] = []

    async def fake_scan(project_id: str) -> object:
        calls.append(project_id)
        return SimpleNamespace(scan_id="scan-webhook", score=812)

    set_webhook_scan_handler(fake_scan)
    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "repository": {"id": 123, "full_name": "octo/example"},
            "installation": {"id": 900},
        }
    ).encode()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-push",
        "X-Hub-Signature-256": _signature(secret, body),
    }
    return TestClient(app), body, headers, calls, previous


def _restore_default_branch_push(
    previous: tuple[
        ProjectStore, GitHubInstallationStore, WebhookAuditStore, WebhookScanJobStore
    ],
) -> None:
    """Restore the globals replaced by :func:`_setup_default_branch_push`."""
    previous_projects, previous_installations, previous_audit, previous_jobs = previous
    set_webhook_scan_handler(scan_project)
    set_webhook_audit_store(previous_audit)
    set_webhook_job_store(previous_jobs)
    set_project_store(previous_projects)
    set_installation_store(previous_installations)


def test_default_branch_push_triggers_one_project_scan(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    client, body, headers, _calls, previous = _setup_default_branch_push(
        tmp_path, monkeypatch
    )
    try:
        first = client.post("/api/github-app/webhook", content=body, headers=headers)
        assert first.status_code == 200
        assert first.json()["scan_triggered"] is True
        assert first.json()["project_id"] == "proj_test"
        assert isinstance(first.json()["job_id"], str)
    finally:
        _restore_default_branch_push(previous)


def test_default_branch_push_deduplicates_repeated_delivery(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    client, body, headers, calls, previous = _setup_default_branch_push(
        tmp_path, monkeypatch
    )
    try:
        first = client.post("/api/github-app/webhook", content=body, headers=headers)
        second = client.post("/api/github-app/webhook", content=body, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert second.json()["scan_triggered"] is False
        assert calls == ["proj_test"]
    finally:
        _restore_default_branch_push(previous)


def test_default_branch_push_records_job_and_audit(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    client, body, headers, _calls, previous = _setup_default_branch_push(
        tmp_path, monkeypatch
    )
    try:
        first = client.post("/api/github-app/webhook", content=body, headers=headers)
        assert first.status_code == 200
        job_id = first.json()["job_id"]

        job = get_webhook_job_store().get(job_id)
        assert job is not None
        assert job.state == "completed"
        assert job.scan_id == "scan-webhook"
        assert job.score == 812
        delivery = get_webhook_audit_store().list()[0]
        assert delivery.outcome == "scan_queued"
        assert delivery.job_id == job_id
    finally:
        _restore_default_branch_push(previous)


def test_non_default_branch_push_does_not_trigger_scan(tmp_path: Path, monkeypatch: object) -> None:
    secret = "webhook-secret"
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)  # type: ignore[attr-defined]
    previous_projects = get_project_store()
    previous_installations = get_installation_store()
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
    installation_store = GitHubInstallationStore(tmp_path / "installations.json")
    installation_store.upsert(
        GitHubInstallation(901, "octo", "Organization", "now", "now")
    )
    set_installation_store(installation_store)
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
    calls: list[str] = []

    async def fake_scan(project_id: str) -> object:
        calls.append(project_id)
        return SimpleNamespace(scan_id="should-not-run", score=0)

    set_webhook_scan_handler(fake_scan)
    body = json.dumps(
        {
            "ref": "refs/heads/feature/example",
            "repository": {"id": 123, "full_name": "octo/example"},
            "installation": {"id": 901},
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
        assert response.json()["job_id"] is None
        assert calls == []
    finally:
        set_webhook_scan_handler(scan_project)
        set_webhook_audit_store(previous_audit)
        set_project_store(previous_projects)
        set_installation_store(previous_installations)
