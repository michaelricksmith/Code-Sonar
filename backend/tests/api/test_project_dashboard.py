"""Project-scoped scan and dashboard API invariants."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.history import InMemoryHistoryStore
from app.main import app, get_history_store, set_history_store
from app.projects import ProjectRecord, ProjectStore, get_project_store, set_project_store


def test_project_scan_updates_dashboard_without_exposing_checkout_path(
    tmp_path,
    test_repo_fixture,
) -> None:
    previous_history = get_history_store()
    previous_projects = get_project_store()
    history = InMemoryHistoryStore()
    projects = ProjectStore(tmp_path / "projects.json")
    project = ProjectRecord(
        project_id="proj_test",
        provider="github",
        owner="example",
        name="repo",
        default_branch="main",
        connected_at=datetime.now(timezone.utc).isoformat(),
        local_checkout_path=str(test_repo_fixture),
    )
    projects.upsert(project)
    set_history_store(history)
    set_project_store(projects)

    try:
        client = TestClient(app)
        response = client.post("/api/projects/proj_test/scan")
        assert response.status_code == 200
        scan = response.json()
        assert scan["repository"] == "example/repo"
        assert scan["scan_id"]
        assert str(test_repo_fixture) not in response.text

        stored = projects.get("proj_test")
        assert stored is not None
        assert stored.latest_scan_id == scan["scan_id"]
        assert stored.latest_score == scan["score"]

        dashboard_response = client.get("/api/projects/proj_test/dashboard")
        assert dashboard_response.status_code == 200
        dashboard = dashboard_response.json()
        assert dashboard["project"]["project_id"] == "proj_test"
        assert dashboard["latest_scan"]["scan_id"] == scan["scan_id"]
        assert dashboard["history_count"] == 1
        assert dashboard["local_checkout_path_exposed"] is False
        assert dashboard["deterministic_score_authority"] == "code_sonar"
        assert "repository_path" not in dashboard["latest_scan"]
        assert str(test_repo_fixture) not in dashboard_response.text
    finally:
        set_history_store(previous_history)
        set_project_store(previous_projects)


def test_unknown_project_is_not_scanned() -> None:
    client = TestClient(app)
    response = client.post("/api/projects/proj_missing/scan")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
