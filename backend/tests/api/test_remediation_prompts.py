"""API tests for prompt-first remediation (fix-prompt generation + copy tracking)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.fix_tracking.models import FixAttempt
from app.fix_tracking.runtime import get_fix_attempt_store, set_fix_attempt_store
from app.fix_tracking.service import reconcile_verified_fixes, user_fix_stats
from app.fix_tracking.store import InMemoryFixAttemptStore
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


@pytest.fixture(autouse=True)
def _signed_in_user(monkeypatch: pytest.MonkeyPatch):
    import app.oauth as oauth_module

    monkeypatch.setattr(
        oauth_module, "current_user", lambda r: SimpleNamespace(id="test-user")
    )


@pytest.fixture()
def isolated_fix_attempts():
    original = get_fix_attempt_store()
    store = InMemoryFixAttemptStore()
    set_fix_attempt_store(store)
    try:
        yield store
    finally:
        set_fix_attempt_store(original)


def _backdate_copies(store: InMemoryFixAttemptStore, copied_at: str) -> None:
    for attempt in store.list_by_user("test-user"):
        attempt.copied_at = copied_at


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
    def test_copied_attempt_recorded_with_user(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
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
        body = response.json()
        assert body["ok"] is True
        assert body["attempt_id"]
        attempts = isolated_fix_attempts.list_by_user("test-user")
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.attempt_id == body["attempt_id"]
        assert attempt.finding_id == "finding-1"
        assert attempt.rule_id == "secrets:hardcoded"
        assert attempt.file_path == "src/app.py"
        assert attempt.scan_id == "scan-1"
        assert (
            attempt.repository_id == compute_repository_id_for_slug("owner/repo")
        )
        assert not attempt.verified

    def test_copied_requires_sign_in(
        self,
        isolated_fix_attempts: InMemoryFixAttemptStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        response = _client().post(
            "/api/remediation/prompt-copied",
            json={
                "repository": "owner/repo",
                "finding_id": "finding-1",
                "rule_id": "secrets:hardcoded",
                "file_path": "src/app.py",
            },
        )
        assert response.status_code == 401
        assert isolated_fix_attempts.list_by_user("test-user") == []


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
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
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
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
    ) -> None:
        # Backdate the copy so the scan below counts as "since the copy".
        self._copy()
        _backdate_copies(isolated_fix_attempts, "2026-01-01T00:00:00+00:00")

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
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
    ) -> None:
        self._copy()
        _backdate_copies(isolated_fix_attempts, "2026-01-01T00:00:00+00:00")

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
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
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

    def test_status_requires_sign_in(
        self, isolated_fix_attempts: InMemoryFixAttemptStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        response = _client().get(
            "/api/remediation/prompt-status", params={"repository": "owner/repo"}
        )
        assert response.status_code == 401


def _mk_attempt(**overrides: object) -> FixAttempt:
    data: dict[str, object] = {
        "attempt_id": "attempt-1",
        "user_id": "test-user",
        "repository_id": compute_repository_id_for_slug("owner/repo"),
        "finding_id": "finding-1",
        "rule_id": "secrets:hardcoded",
        "file_path": "src/app.py",
        "copied_at": "2026-01-01T00:00:00+00:00",
        "scan_id": "scan-old",
    }
    data.update(overrides)
    return FixAttempt.from_dict(data)


class TestInMemoryFixAttemptStore:
    def test_list_open_excludes_verified(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
        store = isolated_fix_attempts
        store.append(_mk_attempt(attempt_id="a1"))
        store.append(_mk_attempt(attempt_id="a2", finding_id="finding-2"))
        repo_id = compute_repository_id_for_slug("owner/repo")
        assert [a.attempt_id for a in store.list_open(repo_id)] == ["a1", "a2"]
        assert store.mark_verified(
            "a1",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-new",
            score_delta=20,
        )
        assert [a.attempt_id for a in store.list_open(repo_id)] == ["a2"]

    def test_mark_verified_is_idempotent(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
        store = isolated_fix_attempts
        store.append(_mk_attempt())
        assert store.mark_verified(
            "attempt-1",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-new",
            score_delta=None,
        )
        assert not store.mark_verified(
            "attempt-1",
            verified_at="2026-06-02T00:00:00+00:00",
            verified_scan_id="scan-newer",
            score_delta=None,
        )
        assert not store.mark_verified(
            "no-such-attempt",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-new",
            score_delta=None,
        )

    def test_list_by_user_filters(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
        store = isolated_fix_attempts
        store.append(_mk_attempt(attempt_id="a1", user_id="alice"))
        store.append(_mk_attempt(attempt_id="a2", user_id="bob"))
        assert [a.attempt_id for a in store.list_by_user("alice")] == ["a1"]
        assert store.list_by_user("carol") == []
        store.mark_verified(
            "a1",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-new",
            score_delta=5,
        )
        assert [a.attempt_id for a in store.list_by_user("alice", verified_only=True)] == ["a1"]
        assert store.list_by_user("bob", verified_only=True) == []


class TestReconcileVerifiedFixes:
    def _seed_scan(
        self,
        history: InMemoryHistoryStore,
        scan_id: str,
        scanned_at: str,
        findings: list[FindingSnapshot],
    ) -> ScanRecord:
        record = _mk_record(
            scan_id=scan_id,
            repository_id=compute_repository_id_for_slug("owner/repo"),
            scanned_at=scanned_at,
            findings=findings,
        )
        history.append(record)
        return record

    def test_verifies_resolved_attempt(
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
    ) -> None:
        repo_id = compute_repository_id_for_slug("owner/repo")
        self._seed_scan(
            isolated_history, "scan-old", "2026-01-02T00:00:00+00:00", [_mk_snapshot()]
        )
        isolated_fix_attempts.append(_mk_attempt(scan_id="scan-old"))
        after = self._seed_scan(
            isolated_history, "scan-new", "2026-06-01T00:00:00+00:00", []
        )
        verified = reconcile_verified_fixes(repo_id, after, isolated_history)
        assert verified == 1
        (attempt,) = isolated_fix_attempts.list_by_user("test-user")
        assert attempt.verified
        assert attempt.verified_scan_id == "scan-new"
        assert attempt.verified_at == "2026-06-01T00:00:00+00:00"

    def test_keeps_open_when_finding_still_present(
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
    ) -> None:
        repo_id = compute_repository_id_for_slug("owner/repo")
        isolated_fix_attempts.append(_mk_attempt(scan_id="scan-old"))
        after = self._seed_scan(
            isolated_history, "scan-new", "2026-06-01T00:00:00+00:00", [_mk_snapshot()]
        )
        assert reconcile_verified_fixes(repo_id, after, isolated_history) == 0
        (attempt,) = isolated_fix_attempts.list_by_user("test-user")
        assert not attempt.verified

    def test_ignores_scan_older_than_copy(
        self,
        isolated_history: InMemoryHistoryStore,
        isolated_fix_attempts: InMemoryFixAttemptStore,
    ) -> None:
        repo_id = compute_repository_id_for_slug("owner/repo")
        isolated_fix_attempts.append(
            _mk_attempt(scan_id="scan-old", copied_at="2026-06-02T00:00:00+00:00")
        )
        after = self._seed_scan(
            isolated_history, "scan-new", "2026-06-01T00:00:00+00:00", []
        )
        assert reconcile_verified_fixes(repo_id, after, isolated_history) == 0

    def test_never_raises_on_broken_store(
        self, isolated_history: InMemoryHistoryStore
    ) -> None:
        class Broken:
            def list_open(self, repository_id: str) -> list[FixAttempt]:
                raise RuntimeError("boom")

        from app.fix_tracking.runtime import set_fix_attempt_store

        set_fix_attempt_store(Broken())  # type: ignore[arg-type]
        try:
            after = self._seed_scan(
                isolated_history, "scan-new", "2026-06-01T00:00:00+00:00", []
            )
            assert (
                reconcile_verified_fixes("repo-id", after, isolated_history) == 0
            )
        finally:
            set_fix_attempt_store(InMemoryFixAttemptStore())


class TestFixTrackingStatsApi:
    def test_stats_require_sign_in(
        self, isolated_fix_attempts: InMemoryFixAttemptStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.oauth as oauth_module

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        assert _client().get("/api/fix-tracking/stats").status_code == 401

    def test_stats_empty(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
        body = _client().get("/api/fix-tracking/stats").json()
        assert body["user_id"] == "test-user"
        assert body["total_verified"] == 0
        assert body["verified_this_week"] == 0
        assert body["best_week"] is None
        assert body["in_progress"] == 0
        assert body["per_repo"] == []

    def test_stats_counts(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
        from datetime import datetime, timezone

        store = isolated_fix_attempts
        now = datetime.now(timezone.utc).isoformat()
        store.append(_mk_attempt(attempt_id="v1", copied_at="2026-01-01T00:00:00+00:00"))
        store.append(_mk_attempt(attempt_id="v2", copied_at="2026-01-01T00:00:00+00:00"))
        store.append(_mk_attempt(attempt_id="open1", copied_at=now))
        for attempt_id in ("v1", "v2"):
            assert store.mark_verified(
                attempt_id,
                verified_at=now,
                verified_scan_id="scan-new",
                score_delta=10,
            )
        body = _client().get("/api/fix-tracking/stats").json()
        assert body["total_verified"] == 2
        assert body["verified_this_week"] == 2
        assert body["in_progress"] == 1
        assert body["best_week"]["count"] == 2
        assert len(body["per_repo"]) == 1
        assert body["per_repo"][0]["verified"] == 2
        assert body["per_repo"][0]["in_progress"] == 1

    def test_user_fix_stats_direct(
        self, isolated_fix_attempts: InMemoryFixAttemptStore
    ) -> None:
        store = isolated_fix_attempts
        store.append(_mk_attempt(attempt_id="v1"))
        store.mark_verified(
            "v1",
            verified_at="2026-06-01T00:00:00+00:00",
            verified_scan_id="scan-new",
            score_delta=15,
        )
        stats = user_fix_stats("test-user")
        assert stats["total_verified"] == 1
        assert stats["best_week"] == {"week_start": "2026-06-01", "count": 1}
        assert user_fix_stats("nobody")["total_verified"] == 0
