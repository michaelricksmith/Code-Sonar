"""Tests for GitHub repository discovery and managed project connection."""

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.github_integration import (
    GitHubIntegration,
    GitHubRepository,
    get_github_integration,
    set_github_integration,
)
from app.main import app
from app.projects import ProjectStore, get_project_store, set_project_store


class FakeGitHubIntegration:
    configured = True
    auth_mode = "app"

    def __init__(self, checkout: Path) -> None:
        self.checkout = checkout
        self.repository = GitHubRepository(
            repository_id=123,
            full_name="octo/example",
            owner="octo",
            name="example",
            default_branch="main",
            private=True,
            clone_url="https://github.com/octo/example.git",
        )

    def list_repositories(self) -> list[GitHubRepository]:
        return [self.repository]

    def get_repository(self, full_name: str) -> GitHubRepository:
        if full_name != self.repository.full_name:
            raise LookupError("GitHub repository is not accessible")
        return self.repository

    def prepare_checkout(self, repository: GitHubRepository) -> Path:
        assert repository == self.repository
        self.checkout.mkdir(parents=True, exist_ok=True)
        return self.checkout


def test_github_app_discovery_uses_installation_repositories_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "repositories": [
                    {
                        "id": 123,
                        "full_name": "octo/example",
                        "default_branch": "main",
                        "private": True,
                        "clone_url": "https://github.com/octo/example.git",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    integration = GitHubIntegration(token="secret", auth_mode="app", client=client)

    repositories = integration.list_repositories()

    assert repositories[0].full_name == "octo/example"
    assert seen[0].url.path == "/installation/repositories"
    assert seen[0].headers["authorization"] == "Bearer secret"


def test_connection_api_never_exposes_token_or_checkout_path(tmp_path: Path) -> None:
    previous_integration = get_github_integration()
    previous_store = get_project_store()
    integration = FakeGitHubIntegration(tmp_path / "managed" / "123")
    set_github_integration(integration)  # type: ignore[arg-type]
    set_project_store(ProjectStore(tmp_path / "projects.json"))
    client = TestClient(app)
    try:
        status = client.get("/api/projects/connect/github/status")
        assert status.status_code == 200
        assert status.json() == {
            "configured": True,
            "auth_mode": "app",
            "app_installable": False,
            "installation_count": 0,
            "webhook_configured": False,
            "token_persisted": False,
            "token_exposed": False,
            "managed_checkout": True,
        }

        repositories = client.get("/api/projects/connect/github/repositories")
        assert repositories.status_code == 200
        repository_payload = repositories.json()
        assert repository_payload["repositories"][0]["full_name"] == "octo/example"
        assert repository_payload["token_exposed"] is False
        assert "authorization" not in str(repository_payload).lower()
        assert "secret" not in str(repository_payload)
        assert str(tmp_path) not in str(repository_payload)

        connected = client.post(
            "/api/projects/connect/github/managed",
            json={"repository_full_name": "octo/example"},
        )
        assert connected.status_code == 200
        payload = connected.json()
        assert payload["project"]["full_name"] == "octo/example"
        assert payload["project"]["provider_installation_id"] is None
        assert payload["managed_checkout"] is True
        assert payload["token_persisted"] is False
        assert payload["token_exposed"] is False
        assert payload["local_checkout_path_exposed"] is False
        assert str(tmp_path) not in str(payload)
        assert "secret" not in str(payload)
    finally:
        set_github_integration(previous_integration)
        set_project_store(previous_store)
