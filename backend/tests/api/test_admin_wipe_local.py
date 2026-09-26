"""Guard + behavior tests for the temporary local-data wipe endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin_wipe_local import _WIPE_PATHS, router


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESONAR_HOME", str(tmp_path))
    monkeypatch.setenv("WIPE_TOKEN", "test-token")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_no_token_env_always_404(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESONAR_HOME", str(tmp_path))
    monkeypatch.delenv("WIPE_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/admin/wipe-local-data", headers={"x-wipe-token": "test-token"}
    )
    assert response.status_code == 404


def test_wrong_token_404(client):
    response = client.post(
        "/api/admin/wipe-local-data", headers={"x-wipe-token": "wrong"}
    )
    assert response.status_code == 404


def test_wipe_deletes_user_data_files_but_keeps_oauth_users(client, tmp_path):
    root = tmp_path / ".code-sonar"
    root.mkdir()
    for name in _WIPE_PATHS:
        target = root / name
        if name == "repositories":
            target.mkdir()
            (target / "dummy.txt").write_text("x")
        else:
            target.write_text("{}\n" if name.endswith(".jsonl") else "{}")
    oauth_users = root / "oauth-users.json"
    oauth_users.write_text(json.dumps([{"sub": "user-1"}]))

    response = client.post(
        "/api/admin/wipe-local-data", headers={"x-wipe-token": "test-token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["wiped"] is True
    for name in _WIPE_PATHS:
        assert not (root / name).exists(), name
        assert data["files"][name]["existed"] is True
        assert data["files"][name]["deleted"] is True
    # Sign-in records must survive.
    assert oauth_users.exists()
    assert json.loads(oauth_users.read_text())[0]["sub"] == "user-1"


def test_wipe_on_empty_data_root_still_reports_wiped(client):
    response = client.post(
        "/api/admin/wipe-local-data", headers={"x-wipe-token": "test-token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["wiped"] is True
    assert all(not info["existed"] for info in data["files"].values())


def test_data_root_respects_codesonar_home(monkeypatch, tmp_path):
    from app.admin_wipe_local import _data_root

    monkeypatch.setenv("CODESONAR_HOME", str(tmp_path))
    assert _data_root() == Path(str(tmp_path)) / ".code-sonar"
