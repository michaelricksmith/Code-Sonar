"""Regression tests for the authenticated API and repository boundary."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.github_app import (
    WebhookAuditStore,
    get_webhook_audit_store,
    set_webhook_audit_store,
)
from app.main import app
from app.remediation.contracts import RemediationRequest
from app.remediation.workspace import GitWorktreeManager
from app.security import RepositoryValidationError
from app.security.runtime import configured_origins, validate_runtime_security_config


def test_api_requires_and_accepts_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    monkeypatch.setenv("CODESONAR_API_TOKEN", "correct-token")
    client = TestClient(app)
    assert client.get("/api/analyzers").status_code == 401
    assert client.get(
        "/api/analyzers", headers={"Authorization": "Bearer correct-token"}
    ).status_code == 200


def test_non_local_startup_fails_closed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODESONAR_API_TOKEN", raising=False)
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "1")
    monkeypatch.setenv("CODESONAR_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError, match="API_TOKEN is required"):
        validate_runtime_security_config()


def test_cors_rejects_hostile_origin_and_honors_exact_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODESONAR_CORS_ORIGINS", "https://console.example.test")
    client = TestClient(app)
    hostile = client.get("/api/analyzers", headers={"Origin": "https://evil.test"})
    assert hostile.status_code == 403
    response = client.get(
        "/api/analyzers", headers={"Origin": "https://console.example.test"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://console.example.test"
    assert configured_origins() == ("https://console.example.test",)


def test_scan_root_rejects_scan_hotspot_and_remediation_source_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setenv("CODESONAR_SCAN_ROOT", str(allowed))
    monkeypatch.setenv("CODESONAR_UNSAFE_ALLOW_ANY_SCAN_PATH", "0")
    client = TestClient(app)
    assert client.post("/api/scan", json={"repo_path": str(outside)}).status_code == 400
    assert client.get("/api/hotspots", params={"repo_path": str(outside)}).status_code == 400
    request = RemediationRequest(
        request_id="request-1",
        finding_id="finding-1",
        repository_path=str(outside),
        scan_id="scan-1",
        instruction="Apply the approved fix",
        approved=True,
    )
    with pytest.raises(RepositoryValidationError, match="outside the allowed scan root"):
        GitWorktreeManager(root=tmp_path / "worktrees").prepare(request)


def test_webhook_hmac_is_not_replaced_by_api_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "webhook-secret"
    body = b'{}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    monkeypatch.setenv("CODESONAR_API_TOKEN", "api-token")
    monkeypatch.setenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", secret)
    previous_audit = get_webhook_audit_store()
    set_webhook_audit_store(WebhookAuditStore(tmp_path / "audit.jsonl"))
    try:
        response = TestClient(app).post(
            "/api/github-app/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": signature,
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "delivery-1",
            },
        )
        assert response.status_code != 401
    finally:
        set_webhook_audit_store(previous_audit)
