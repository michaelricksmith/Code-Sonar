"""Tests for async scan jobs: lifecycle, real scan pipeline, error handling."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import oauth as oauth_module
from app import scan_jobs
from app.main import app, get_history_store
from app.oauth import OAuthUserStore, new_session_token, set_oauth_user_store

_TEST_SECRET = "test-session-secret"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_clone(monkeypatch: pytest.MonkeyPatch):
    """Replace git cloning with a local fixture-repo copy."""
    seen: dict[str, Any] = {}

    def _clone(clone_url: str, branch: str | None, dest: Path) -> None:
        seen["clone_url"] = clone_url
        seen["branch"] = branch
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.py").write_text(
            '"""Fixture repo."""\n\n\n# TODO: clean this up\n'
            "def process(items):\n"
            "    result = []\n"
            "    for item in items:\n"
            "        if item:\n"
            "            result.append(item * 2)\n"
            "    return result\n",
            encoding="utf-8",
        )

    previous = scan_jobs._clone_repo
    scan_jobs.set_clone_repo(_clone)
    yield seen
    scan_jobs.set_clone_repo(previous)


@pytest.fixture
def signed_in_github_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str]:
    monkeypatch.setenv("SONAR_SESSION_SECRET", _TEST_SECRET)
    monkeypatch.setattr(oauth_module, "_secret_warning_emitted", True)
    store = OAuthUserStore(path=tmp_path / "oauth-users.json")
    previous = oauth_module.get_oauth_user_store()
    set_oauth_user_store(store)
    user = store.upsert(
        provider="github",
        provider_user_id="4242",
        name="Mike S",
        email="mike@example.com",
        avatar_url="",
        github_access_token="secret-token-xyz",
    )
    yield {
        "cookie": f"sonar_session={new_session_token(user.id, _TEST_SECRET)}",
        "token": "secret-token-xyz",
    }
    set_oauth_user_store(previous)


def _wait_for(client: TestClient, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/scan-job/{job_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.2)
    raise TimeoutError(f"scan job {job_id} did not finish in {timeout}s")


class TestScanJobLifecycle:
    def test_create_returns_job_id(self, client, fake_clone):
        response = client.post("/api/scan-job", json={"repo": "octo/hello"})
        assert response.status_code == 200
        assert "job_id" in response.json()

    def test_full_lifecycle_runs_real_pipeline(
        self, client, fake_clone, signed_in_github_user
    ):
        created = client.post(
            "/api/scan-job",
            json={"repo": "octo/hello", "branch": "main"},
            headers={"Cookie": signed_in_github_user["cookie"]},
        )
        job_id = created.json()["job_id"]

        data = _wait_for(client, job_id)
        assert data["status"] == "done"
        assert data["step"] == "Done — your score is ready."
        assert data["progress"] == 1.0

        result = data["result"]
        assert result["score"] > 0
        assert result["grade"] in ("A", "B", "C", "D", "F")
        assert result["finding_count"] >= 1
        assert result["scan_id"]
        # Persisted through the existing history mechanism.
        assert get_history_store().get(result["scan_id"]) is not None

        # The OAuth token was used server-side for the clone but never leaks.
        assert "secret-token-xyz" in fake_clone["clone_url"]
        assert "secret-token-xyz" not in str(data)
        status_now = client.get(f"/api/scan-job/{job_id}").json()
        assert "secret-token-xyz" not in str(status_now)

    def test_repo_url_form_accepted(self, client, fake_clone):
        response = client.post(
            "/api/scan-job",
            json={"repo": "https://github.com/octo/hello.git"},
        )
        assert response.status_code == 200
        data = _wait_for(client, response.json()["job_id"])
        assert data["status"] == "done"

    def test_invalid_repo_rejected(self, client, fake_clone):
        response = client.post("/api/scan-job", json={"repo": "not a repo!!"})
        assert response.status_code == 400

    def test_ssh_url_rejected(self, client, fake_clone):
        response = client.post(
            "/api/scan-job", json={"repo": "git@github.com:octo/hello.git"}
        )
        assert response.status_code == 400

    def test_unknown_job_is_404(self, client):
        assert client.get("/api/scan-job/" + "a" * 32).status_code == 404
        assert client.get("/api/scan-job/nope").status_code == 404

    def test_clone_failure_surfaces_error(self, client, monkeypatch):
        def _boom(clone_url: str, branch: str | None, dest: Path) -> None:
            raise RuntimeError("clone exploded")

        previous = scan_jobs._clone_repo
        scan_jobs.set_clone_repo(_boom)
        try:
            created = client.post("/api/scan-job", json={"repo": "octo/hello"})
            data = _wait_for(client, created.json()["job_id"])
        finally:
            scan_jobs.set_clone_repo(previous)
        assert data["status"] == "error"
        assert "clone exploded" in data["error"]
