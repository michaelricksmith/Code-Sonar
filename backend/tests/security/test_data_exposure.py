"""API responses must not disclose server filesystem repository paths."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.history import InMemoryHistoryStore, build_scan_record
from app.main import app, set_history_store
from app.scoring.engine import calculate_score


def test_history_endpoints_do_not_expose_repository_path(tmp_path: Path) -> None:
    secret_path = str(tmp_path / "customer-secret-repository")
    record = build_scan_record(
        repository_id="repository-1",
        repository_path=secret_path,
        findings=[],
        scoring=calculate_score([]),
        scan_id="scan-secret-path",
    )
    store = InMemoryHistoryStore()
    store.append(record)
    set_history_store(store)
    client = TestClient(app)

    for url in ("/api/history/list", "/api/history/scan-secret-path"):
        response = client.get(url)
        assert response.status_code == 200
        assert secret_path not in response.text
        assert "repository_path" not in response.text


def test_manual_scan_uses_repository_name_not_host_path(tmp_path: Path) -> None:
    repository = tmp_path / "private-parent" / "visible-repository"
    repository.mkdir(parents=True)
    response = TestClient(app).post("/api/scan", json={"repo_path": str(repository)})

    assert response.status_code == 200
    assert response.json()["repository"] == "visible-repository"
    assert str(tmp_path) not in response.text
