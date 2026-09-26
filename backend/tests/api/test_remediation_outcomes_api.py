"""API tests for recording observed remediation outcomes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml.outcomes import JsonlOutcomeStore
from app.ml.outcomes.runtime import set_outcome_store


@pytest.fixture(autouse=True)
def reset_store() -> None:
    set_outcome_store(None)
    yield
    set_outcome_store(None)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    set_outcome_store(JsonlOutcomeStore(tmp_path / "outcomes.jsonl"))
    return TestClient(app)


def _payload() -> dict[str, object]:
    return {
        "outcome_id": "outcome-1",
        "repository_id": "repo-1",
        "finding_id": "finding-1",
        "before_scan_id": "scan-before",
        "after_scan_id": "scan-after",
        "attempted_at": "2026-08-30T20:30:00+00:00",
        "executor": "cursor",
        "remediation_kind": "automated_patch",
        "build_passed": True,
        "tests_passed": True,
        "finding_resolved": True,
        "finding_reintroduced": False,
        "regression_detected": False,
        "score_delta": 18,
        "debt_points_delta": -12,
    }


def test_record_outcome_returns_high_trust_label_without_execution(client: TestClient) -> None:
    response = client.post("/api/ml/remediation-outcomes", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"]["successful"] is True
    assert data["training_label"]["task"] == "remediation_success"
    assert data["training_label"]["value"] == "1"
    assert data["training_label"]["trust_tier"] == "remediation_outcome"
    assert data["training_label"]["is_proxy"] is False
    assert data["deterministic_score_unchanged"] is True
    assert data["execution_performed"] is False


def test_duplicate_outcome_is_rejected(client: TestClient) -> None:
    assert client.post("/api/ml/remediation-outcomes", json=_payload()).status_code == 200

    response = client.post("/api/ml/remediation-outcomes", json=_payload())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "remediation_outcome_exists"


def test_recorded_outcome_can_be_read_back(client: TestClient) -> None:
    client.post("/api/ml/remediation-outcomes", json=_payload())

    response = client.get("/api/ml/remediation-outcomes/outcome-1")

    assert response.status_code == 200
    assert response.json()["score_delta"] == 18
    assert response.json()["debt_points_delta"] == -12


def test_missing_outcome_returns_404(client: TestClient) -> None:
    response = client.get("/api/ml/remediation-outcomes/missing")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "remediation_outcome_not_found"


def _payload_for(slug: str, outcome_id: str, attempted_at: str) -> dict[str, object]:
    from app.history import compute_repository_id_for_slug

    payload = _payload()
    payload["outcome_id"] = outcome_id
    payload["repository_id"] = compute_repository_id_for_slug(slug)
    payload["attempted_at"] = attempted_at
    return payload


def test_list_outcomes_resolves_repo_slug_newest_first(client: TestClient) -> None:
    slug = "michaelricksmith/Code-Sonar"
    client.post(
        "/api/ml/remediation-outcomes",
        json=_payload_for(slug, "o-old", "2026-08-30T20:30:00+00:00"),
    )
    client.post(
        "/api/ml/remediation-outcomes",
        json=_payload_for(slug, "o-new", "2026-08-31T20:30:00+00:00"),
    )

    response = client.get("/api/ml/remediation-outcomes", params={"repo": slug})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert [o["outcome_id"] for o in data["outcomes"]] == ["o-new", "o-old"]
    assert data["outcomes"][0]["successful"] is True


def test_list_outcomes_is_scoped_to_repo(client: TestClient) -> None:
    client.post(
        "/api/ml/remediation-outcomes",
        json=_payload_for("owner/a", "o-a", "2026-08-30T20:30:00+00:00"),
    )
    client.post(
        "/api/ml/remediation-outcomes",
        json=_payload_for("owner/b", "o-b", "2026-08-30T20:30:00+00:00"),
    )

    response = client.get("/api/ml/remediation-outcomes", params={"repo": "owner/a"})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["outcomes"][0]["outcome_id"] == "o-a"


def test_list_outcomes_empty_repo_returns_empty_list(client: TestClient) -> None:
    response = client.get("/api/ml/remediation-outcomes", params={"repo": "owner/never-scanned"})

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["outcomes"] == []


def test_list_outcomes_respects_limit(client: TestClient) -> None:
    slug = "owner/many"
    for i in range(5):
        client.post(
            "/api/ml/remediation-outcomes",
            json=_payload_for(slug, f"o-{i}", f"2026-08-3{i}T20:30:00+00:00"),
        )

    response = client.get("/api/ml/remediation-outcomes", params={"repo": slug, "limit": 2})

    assert response.status_code == 200
    # count is the repo-wide total; the list itself is the newest-first page.
    assert response.json()["count"] == 5
    assert len(response.json()["outcomes"]) == 2
    assert [o["outcome_id"] for o in response.json()["outcomes"]] == ["o-4", "o-3"]
