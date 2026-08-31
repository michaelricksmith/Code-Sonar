from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.github_app import InstallationStore, set_installation_store, verify_webhook_signature
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    set_installation_store(InstallationStore(tmp_path / "installations.json"))
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    return TestClient(app)


def _signature(body: bytes) -> str:
    return "sha256=" + hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()


def test_webhook_rejects_invalid_signature(client: TestClient) -> None:
    response = client.post(
        "/api/github-app/webhook",
        content=b"{}",
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=bad"},
    )
    assert response.status_code == 401


def test_installation_webhook_persists_identity_not_secrets(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "created",
            "installation": {
                "id": 42,
                "account": {"login": "octocat", "type": "User"},
            },
        }
    ).encode()
    response = client.post(
        "/api/github-app/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    status = client.get("/api/github-app/status").json()
    assert status["installation_count"] == 1
    assert status["installations"][0]["installation_id"] == 42
    serialized = json.dumps(status).lower()
    assert "test-webhook-secret" not in serialized
    assert "private_key_exposed" in serialized
    assert status["private_key_exposed"] is False
    assert status["installation_token_persisted"] is False


def test_push_webhook_schedules_rescan(client: TestClient, monkeypatch) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr("app.github_app._rescan_project", scheduled.append)
    body = json.dumps({"repository": {"full_name": "octocat/hello-world"}}).encode()
    response = client.post(
        "/api/github-app/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-2",
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["rescan_scheduled"] is True
    assert scheduled == ["octocat/hello-world"]


def test_signature_helper_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", raising=False)
    with pytest.raises(PermissionError):
        verify_webhook_signature(b"{}", None)
