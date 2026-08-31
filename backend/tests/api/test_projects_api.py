"""Project connection API invariants."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.projects import ProjectRecord, ProjectStore, set_project_store


def _client(tmp_path: Path) -> TestClient:
    set_project_store(ProjectStore(tmp_path / "projects.json"))
    return TestClient(app)


def test_project_list_does_not_expose_local_checkout_path(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects.json")
    store.upsert(
        ProjectRecord(
            project_id="proj_test",
            provider="github",
            owner="acme",
            name="service",
            default_branch="main",
            connected_at="2026-08-31T00:00:00+00:00",
            local_checkout_path="/secret/host/path",
        )
    )
    set_project_store(store)

    response = TestClient(app).get("/api/projects")

    assert response.status_code == 200
    project = response.json()["projects"][0]
    assert project["project_id"] == "proj_test"
    assert project["full_name"] == "acme/service"
    assert "local_checkout_path" not in project
    assert "/secret/host/path" not in response.text


def test_get_unknown_project_returns_404(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/projects/missing")

    assert response.status_code == 404


def test_connect_github_rejects_missing_checkout(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/api/projects/connect/github",
        json={
            "owner": "acme",
            "name": "service",
            "local_checkout_path": str(tmp_path / "missing"),
        },
    )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]
