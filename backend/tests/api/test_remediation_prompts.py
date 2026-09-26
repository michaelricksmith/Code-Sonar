"""API tests for prompt-first remediation (fix-prompt generation + copy tracking)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.history import SCHEMA_VERSION
from app.history.history_store import InMemoryHistoryStore
from app.history.repository_identity import compute_repository_id_for_slug
from app.history.scan_record import FindingSnapshot, ScanRecord
from app.main import app, set_history_store


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _finding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "finding-1",
        "rule_id": "secrets:hardcoded",
        "category": "security",
        "severity": "error",
        "file_path": "src/app.py",
        "line_start": 12,
        "line_end": 14,
        "symbol": "load_config",
        "evidence": 'api_key = "sk-live-abc123"',
        "message": "A live API key is hardcoded in the source.",
        "suggestion": "Move the key into an environment variable.",
        "analyzer": "secrets",
    }
    payload.update(overrides)
    return payload


def _events_file(tmp_home: Path) -> Path:
    return tmp_home / ".code-sonar" / "prompt-events.jsonl"


def _read_events(tmp_home: Path) -> list[dict[str, object]]:
    path = _events_file(tmp_home)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _mk_snapshot(**overrides: object) -> FindingSnapshot:
    data: dict[str, object] = {
        "id": "finding-1",
        "rule_id": "secrets:hardcoded",
        "category": "security",
        "severity": "error",
        "confidence": 1.0,
        "file_path": "src/app.py",
        "line_start": 12,
        "line_end": 14,
        "symbol": "load_config",
        "evidence": "redacted",
        "message": "A live API key is hardcoded in the source.",
        "suggestion": "Move the key into an environment variable.",
        "debt_points": 10,
        "analyzer": "secrets",
        "metadata": {},
    }
    data.update(overrides)
    return FindingSnapshot.from_dict(data)


def _mk_record(
    *,
    scan_id: str,
    repository_id: str,
    scanned_at: str,
    findings: list[FindingSnapshot],
) -> ScanRecord:
    return ScanRecord.from_dict(
        {
            "scan_id": scan_id,
            "repository_id": repository_id,
            "repository_path": "/tmp/repo",
            "repository_slug": "owner/repo",
            "scanned_at": scanned_at,
            "schema_version": SCHEMA_VERSION,
            "score": 540,
            "grade": "C",
            "total_debt_points": sum(f.debt_points for f in findings),
            "finding_count": len(findings),
            "category_scores": {},
            "severity_distribution": {},
            "findings_by_category": {},
            "findings_source_breakdown": {"source": 0, "test": 0, "fixture": 0},
            "findings": [f.to_dict() for f in findings],
        }
    )


@pytest.fixture()
def isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    monkeypatch.setenv("CODESONAR_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def isolated_history():
    from app.main import get_history_store

    original = get_history_store()
    store = InMemoryHistoryStore()
    set_history_store(store)
    try:
        yield store
    finally:
        set_history_store(original)


class TestFixPrompt:
    def test_prompt_contains_grounding(self, isolated_home: Path) -> None:
        response = _client().post(
            "/api/remediation/fix-prompt",
            json={
                "repository": "owner/repo",
                "scan_id": "scan-1",
                "finding": _finding_payload(),
            },
        )
        assert response.status_code == 200
        prompt = response.json()["prompt"]
        assert "owner/repo" in prompt
        assert "src/app.py" in prompt
        assert "12-14" in prompt
        assert "secrets:hardcoded" in prompt
        assert "secrets" in prompt
        assert "A live API key is hardcoded" in prompt
        assert "Move the key into an environment variable." in prompt

    def test_prompt_contains_anti_rewrite_constraints(
        self, isolated_home: Path
    ) -> None:
        response = _client().post(
            "/api/remediation/fix-prompt",
            json={"repository": "owner/repo", "finding": _finding_payload()},
        )
        prompt = response.json()["prompt"]
        assert "Change ONLY what is needed" in prompt
        assert "Do not add new libraries or dependencies" in prompt
        assert "Re-scan" in prompt and "Code Sonar" in prompt

    def test_prompt_is_deterministic(self, isolated_home: Path) -> None:
        body = {"repository": "owner/repo", "finding": _finding_payload()}
        first = _client().post("/api/remediation/fix-prompt", json=body).json()["prompt"]
        second = _client().post("/api/remediation/fix-prompt", json=body).json()["prompt"]
        assert first == second

    def test_generate_logs_generated_event(self, isolated_home: Path) -> None:
        _client().post(
            "/api/remediation/fix-prompt",
            json={
                "repository": "owner/repo",
                "scan_id": "scan-1",
                "finding": _finding_payload(),
            },
        )
        events = _read_events(isolated_home)
        generated = [e for e in events if e["event"] == "generated"]
        assert len(generated) == 1
        assert generated[0]["rule_id"] == "secrets:hardcoded"
        assert generated[0]["file_path"] == "src/app.py"


class TestPromptCopied:
    def test_copied_event_logged(self, isolated_home: Path) -> None:
        response = _client().post(
            "/api/remediation/prompt-copied",
            json={
                "repository": "owner/repo",
                "scan_id": "scan-1",
                "finding_id": "finding-1",
                "rule_id": "secrets:hardcoded",
                "file_path": "src/app.py",
                "line_start": 12,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        events = _read_events(isolated_home)
        assert len(events) == 1
        assert events[0]["event"] == "copied"
        assert events[0]["finding_id"] == "finding-1"


class TestPromptStatus:
    def _copy(
        self,
        repository: str = "owner/repo",
        rule_id: str = "secrets:hardcoded",
        file_path: str = "src/app.py",
    ) -> None:
        response = _client().post(
            "/api/remediation/prompt-copied",
            json={
                "repository": repository,
                "finding_id": "finding-1",
                "rule_id": rule_id,
                "file_path": file_path,
                "line_start": 12,
            },
        )
        assert response.status_code == 200

    def test_in_progress_when_no_scan_since_copy(
        self, isolated_home: Path, isolated_history: InMemoryHistoryStore
    ) -> None:
        self._copy()
        response = _client().get(
            "/api/remediation/prompt-status", params={"repository": "owner/repo"}
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "in_progress"
        assert items[0]["rule_id"] == "secrets:hardcoded"

    def test_resolved_when_finding_gone_from_newer_scan(
        self, isolated_home: Path, isolated_history: InMemoryHistoryStore
    ) -> None:
        # Backdate the copy event so the scan below counts as "since the copy".
        self._copy()
        path = _events_file(isolated_home)
        lines = path.read_text().splitlines()
        record = json.loads(lines[0])
        record["at"] = "2026-01-01T00:00:00+00:00"
        path.write_text(json.dumps(record) + "\n")

        repo_id = compute_repository_id_for_slug("owner/repo")
        isolated_history.append(
            _mk_record(
                scan_id="scan-new",
                repository_id=repo_id,
                scanned_at="2026-06-01T00:00:00+00:00",
                findings=[],  # finding is gone
            )
        )
        items = (
            _client()
            .get("/api/remediation/prompt-status", params={"repository": "owner/repo"})
            .json()["items"]
        )
        assert items[0]["status"] == "resolved"

    def test_still_open_when_finding_present_in_newer_scan(
        self, isolated_home: Path, isolated_history: InMemoryHistoryStore
    ) -> None:
        self._copy()
        path = _events_file(isolated_home)
        lines = path.read_text().splitlines()
        record = json.loads(lines[0])
        record["at"] = "2026-01-01T00:00:00+00:00"
        path.write_text(json.dumps(record) + "\n")

        repo_id = compute_repository_id_for_slug("owner/repo")
        isolated_history.append(
            _mk_record(
                scan_id="scan-new",
                repository_id=repo_id,
                scanned_at="2026-06-01T00:00:00+00:00",
                findings=[_mk_snapshot()],
            )
        )
        items = (
            _client()
            .get("/api/remediation/prompt-status", params={"repository": "owner/repo"})
            .json()["items"]
        )
        assert items[0]["status"] == "still_open"

    def test_old_scan_does_not_flip_in_progress(
        self, isolated_home: Path, isolated_history: InMemoryHistoryStore
    ) -> None:
        # Scan predates the copy: the user hasn't rescanned since copying.
        repo_id = compute_repository_id_for_slug("owner/repo")
        isolated_history.append(
            _mk_record(
                scan_id="scan-old",
                repository_id=repo_id,
                scanned_at="2020-01-01T00:00:00+00:00",
                findings=[_mk_snapshot()],
            )
        )
        self._copy()
        items = (
            _client()
            .get("/api/remediation/prompt-status", params={"repository": "owner/repo"})
            .json()["items"]
        )
        assert items[0]["status"] == "in_progress"
