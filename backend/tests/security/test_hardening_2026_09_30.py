"""Regression tests for the 2026-09-30 full-platform security hardening.

Each test pins one fixed vulnerability so a future refactor can't silently
re-open it:

- H1  repository-clone SSRF (``_parse_repo_input`` pins clones to github.com)
- H2  cross-user scan access / IDOR (``assert_scan_access`` + owner_user_id)
- H3  short-window rate limits on scan/ask/remediation endpoints
- M1  OAuth token off the process table (``run_git_clone`` + ``clone_token``)
- L1  GitHub App installation remapping across tenants (409)
- L3  interactive API docs disabled in production
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

import app.github_app as github_app_module
import app.oauth as oauth_module
from app import scan_jobs
from app.github_app import GitHubInstallation, set_installation_store
from app.security.git_auth import clone_token, get_clone_token, run_git_clone
from app.security.ownership import assert_scan_access
from app.security.rate_limit import check_rate_limit, reset_rate_limits
from app.security.tenant import bind_tenant, reset_tenant

# ---------------------------------------------------------------------------
# H1: repository-clone SSRF
# ---------------------------------------------------------------------------


class TestRepoUrlSsrfGuard:
    def test_arbitrary_host_rejected(self) -> None:
        with pytest.raises(ValueError, match="Only github.com"):
            scan_jobs._parse_repo_input("https://evil.example.com/octocat/Hello-World.git")

    def test_ip_literal_rejected(self) -> None:
        with pytest.raises(ValueError, match="Only github.com"):
            scan_jobs._parse_repo_input("https://127.0.0.1/octocat/Hello-World.git")

    def test_userinfo_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not contain credentials"):
            scan_jobs._parse_repo_input("https://x-access-token:abc@github.com/o/r.git")

    def test_explicit_port_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not specify a port"):
            scan_jobs._parse_repo_input("https://github.com:8443/o/r.git")

    def test_dot_segments_yield_no_slug(self) -> None:
        # Path-traversal segments can never become a usable repository slug,
        # so remediation can never be tricked into re-cloning them.
        assert scan_jobs._repository_slug("https://github.com/../etc/passwd.git") is None
        assert scan_jobs._repository_slug("https://github.com/o/r.git") == "o/r"

    def test_host_is_pinned_even_with_crafty_path(self) -> None:
        # The SSRF-relevant property: no path can change the clone host.
        url = scan_jobs._parse_repo_input("https://github.com/../etc/passwd.git")
        assert url.startswith("https://github.com/")

    def test_github_url_accepted(self) -> None:
        url = scan_jobs._parse_repo_input("https://github.com/octocat/Hello-World.git")
        assert url == "https://github.com/octocat/Hello-World.git"

    def test_www_github_url_accepted(self) -> None:
        url = scan_jobs._parse_repo_input("https://www.github.com/octocat/Hello-World")
        assert url == "https://github.com/octocat/Hello-World"
        assert scan_jobs._repository_slug(url) == "octocat/Hello-World"

    def test_slug_form_accepted(self) -> None:
        url = scan_jobs._parse_repo_input("octocat/Hello-World")
        assert url == "https://github.com/octocat/Hello-World.git"


# ---------------------------------------------------------------------------
# M1: OAuth token off the process table
# ---------------------------------------------------------------------------


def test_token_never_in_clone_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The OAuth token travels via env/askpass, never the clone URL argv."""
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["argv"] = list(cmd)
        seen["env"] = dict(kwargs.get("env") or {})

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return Done()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    dest = tmp_path / "repo"
    with clone_token("super-secret-token"):
        run_git_clone("https://github.com/o/r.git", None, dest)
    assert "super-secret-token" not in str(seen["argv"])
    assert seen["env"].get("CODE_SONAR_GIT_TOKEN") == "super-secret-token"
    assert get_clone_token() == ""  # context cleared


# ---------------------------------------------------------------------------
# H2: cross-user scan access / IDOR
# ---------------------------------------------------------------------------


def _owned_record(owner: str | None) -> SimpleNamespace:
    return SimpleNamespace(owner_user_id=owner, scan_id="scan-1")


class TestAssertScanAccess:
    def test_owner_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(oauth_module, "current_user", lambda r: SimpleNamespace(id="a"))
        assert_scan_access(_owned_record("a"), SimpleNamespace())  # no raise

    def test_other_user_gets_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(oauth_module, "current_user", lambda r: SimpleNamespace(id="b"))
        with pytest.raises(HTTPException) as excinfo:
            assert_scan_access(_owned_record("a"), SimpleNamespace())
        assert excinfo.value.status_code == 404

    def test_anonymous_gets_404_on_owned_scan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        with pytest.raises(HTTPException) as excinfo:
            assert_scan_access(_owned_record("a"), SimpleNamespace())
        assert excinfo.value.status_code == 404

    def test_legacy_ownerless_record_keeps_tenant_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        assert_scan_access(_owned_record(None), SimpleNamespace())  # no raise


class TestCrossUserScanIdor:
    """End-to-end: user B must not read user A's scan via /api/history/{id}."""

    @pytest.fixture
    def two_users(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
        from app.oauth import OAuthUserStore, new_session_token, set_oauth_user_store

        secret = "idor-test-secret"
        monkeypatch.setenv("SONAR_SESSION_SECRET", secret)
        monkeypatch.setattr(oauth_module, "_secret_warning_emitted", True)
        store = OAuthUserStore(path=tmp_path / "oauth-users.json")
        previous = oauth_module.get_oauth_user_store()
        set_oauth_user_store(store)
        cookies: dict[str, str] = {}
        user_ids: dict[str, str] = {}
        for provider_id in ("1001", "1002"):
            user = store.upsert(
                provider="github",
                provider_user_id=provider_id,
                name=f"User {provider_id}",
                email=f"{provider_id}@example.com",
                avatar_url="",
                github_access_token=None,
            )
            cookies[provider_id] = f"sonar_session={new_session_token(user.id, secret)}"
            user_ids[provider_id] = user.id
        yield {"cookies": cookies, "user_ids": user_ids}
        set_oauth_user_store(previous)

    def test_user_b_gets_404_for_user_a_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, two_users: dict
    ) -> None:
        import app.main as main_module
        from app.history import JsonlHistoryStore, build_scan_record
        from app.scoring.engine import calculate_score

        client = TestClient(main_module.app, raise_server_exceptions=False)

        store = JsonlHistoryStore(tmp_path / "history.jsonl")
        previous = main_module.get_history_store()
        main_module.set_history_store(store)
        try:
            record = build_scan_record(
                repository_id="repo-a",
                repository_path="/tmp/repo-a",
                findings=[],
                scoring=calculate_score([]),
                scan_id="scan-owned-by-a",
                scanned_at="2026-09-30T00:00:00+00:00",
                owner_user_id=two_users["user_ids"]["1001"],
            )
            store.append(record)

            cookies = two_users["cookies"]
            ok = client.get(
                "/api/history/scan-owned-by-a",
                headers={"Cookie": cookies["1001"]},
            )
            assert ok.status_code == 200

            # Another signed-in user gets 404 (not 403: no existence oracle).
            denied = client.get(
                "/api/history/scan-owned-by-a",
                headers={"Cookie": cookies["1002"]},
            )
            assert denied.status_code == 404

            anon = client.get("/api/history/scan-owned-by-a")
            assert anon.status_code == 404
        finally:
            main_module.set_history_store(previous)


# ---------------------------------------------------------------------------
# H3: short-window rate limits
# ---------------------------------------------------------------------------


def _request_for_ip(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/ask-sonar/ask",
            "headers": [],
            "client": (ip, 0),
        }
    )


class TestRateLimit:
    def test_allows_up_to_limit_then_429s(self) -> None:
        reset_rate_limits()
        try:
            for _ in range(3):
                check_rate_limit(_request_for_ip("10.0.0.1"), limit=3, window_seconds=60)
            with pytest.raises(HTTPException) as excinfo:
                check_rate_limit(_request_for_ip("10.0.0.1"), limit=3, window_seconds=60)
            assert excinfo.value.status_code == 429
            assert "Retry-After" in excinfo.value.headers
        finally:
            reset_rate_limits()

    def test_keys_are_isolated_per_ip(self) -> None:
        reset_rate_limits()
        try:
            check_rate_limit(_request_for_ip("10.0.0.1"), limit=1, window_seconds=60)
            check_rate_limit(_request_for_ip("10.0.0.2"), limit=1, window_seconds=60)  # ok
            with pytest.raises(HTTPException):
                check_rate_limit(_request_for_ip("10.0.0.1"), limit=1, window_seconds=60)
        finally:
            reset_rate_limits()

    def test_keys_are_isolated_per_limit(self) -> None:
        reset_rate_limits()
        try:
            check_rate_limit(_request_for_ip("10.0.0.1"), limit=1, window_seconds=60)
            # A different limit/window is a different bucket.
            check_rate_limit(_request_for_ip("10.0.0.1"), limit=5, window_seconds=3600)
        finally:
            reset_rate_limits()


# ---------------------------------------------------------------------------
# L1: GitHub App installation cross-tenant remap -> 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_app_callback_rejects_cross_tenant_remap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.github_app import GitHubInstallationStore

    store = GitHubInstallationStore(tmp_path / "installations.json")
    token = bind_tenant("tenant-a")
    store.upsert(
        GitHubInstallation(
            installation_id=7,
            account_login="octo",
            account_type="User",
            installed_at="2026-09-30T00:00:00+00:00",
            updated_at="2026-09-30T00:00:00+00:00",
        )
    )
    reset_tenant(token)
    previous = github_app_module.get_installation_store()
    set_installation_store(store)
    token = bind_tenant("tenant-b")
    try:
        monkeypatch.setattr(github_app_module, "_verify_install_state", lambda s: True)
        monkeypatch.setattr(
            github_app_module,
            "get_github_app_auth",
            lambda: SimpleNamespace(
                installation_details=lambda iid: {
                    "account": {"login": "octo", "type": "User"},
                    "repository_selection": "selected",
                }
            ),
        )
        monkeypatch.setattr(github_app_module, "set_active_installation_id", lambda iid: None)
        with pytest.raises(HTTPException) as excinfo:
            await github_app_module.github_app_callback(
                installation_id=7, setup_action="install", state="ok"
            )
        assert excinfo.value.status_code == 409
    finally:
        reset_tenant(token)
        set_installation_store(previous)


# ---------------------------------------------------------------------------
# L3: docs disabled in production
# ---------------------------------------------------------------------------


def test_docs_disabled_when_sonar_env_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    monkeypatch.setenv("SONAR_ENV", "production")
    try:
        importlib.reload(main_module)
        assert main_module.app.docs_url is None
        assert main_module.app.redoc_url is None
        assert main_module.app.openapi_url is None
    finally:
        monkeypatch.delenv("SONAR_ENV", raising=False)
        importlib.reload(main_module)
    # Dev default keeps the docs available.
    assert main_module.app.docs_url == "/docs"


class TestCommitShaTracking:
    def test_build_scan_record_carries_commit_sha(self) -> None:
        from app.history import build_scan_record
        from app.scoring.engine import calculate_score

        record = build_scan_record(
            repository_id="repo-x",
            repository_path="/tmp/repo-x",
            findings=[],
            scoring=calculate_score([]),
            scan_id="sha-test",
            commit_sha="a" * 40,
        )
        assert record.commit_sha == "a" * 40
        assert record.to_dict()["commit_sha"] == "a" * 40

    def test_from_dict_tolerates_legacy_records_without_sha(self) -> None:
        from app.history import ScanRecord, build_scan_record
        from app.scoring.engine import calculate_score

        record = build_scan_record(
            repository_id="repo-x",
            repository_path="/tmp/repo-x",
            findings=[],
            scoring=calculate_score([]),
            scan_id="sha-legacy",
        )
        data = record.to_dict()
        del data["commit_sha"]
        restored = ScanRecord.from_dict(data)
        assert restored.commit_sha is None

    def test_head_commit_sha_fail_soft(self, tmp_path: Path) -> None:
        from app.scan_jobs import _head_commit_sha

        assert _head_commit_sha(tmp_path) is None  # not a git repo


class TestGroqKeyPrecedence:
    """An OpenAI key must never be sent to a Groq endpoint (401 → silent
    deterministic fallback). Key selection must follow the base URL."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch):
        from app.ask_sonar.runtime import set_answer_provider

        for var in (
            "ASK_SONAR_PROVIDER",
            "CODE_SONAR_ASK_PROVIDER",
            "ASK_SONAR_BASE_URL",
            "ASK_SONAR_MODEL",
            "OPENAI_API_KEY",
            "GROQ_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)
        set_answer_provider(None)
        yield
        set_answer_provider(None)

    def _configure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.ask_sonar.runtime import configure_answer_provider_from_env

        monkeypatch.setenv("ASK_SONAR_PROVIDER", "openai")
        monkeypatch.setenv("ASK_SONAR_BASE_URL", "https://api.groq.com/openai/v1")
        monkeypatch.setenv("ASK_SONAR_MODEL", "llama-3.3-70b-versatile")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-stale")
        monkeypatch.setenv("GROQ_API_KEY", "gsk-groq-live")
        configure_answer_provider_from_env()

    def test_groq_endpoint_uses_groq_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.ask_sonar.runtime import get_answer_provider

        self._configure(monkeypatch)
        provider = get_answer_provider()
        assert provider is not None
        assert provider.api_key == "gsk-groq-live"

    def test_openai_endpoint_uses_openai_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.ask_sonar.runtime import get_answer_provider

        monkeypatch.setenv("ASK_SONAR_PROVIDER", "openai")
        monkeypatch.setenv("ASK_SONAR_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("ASK_SONAR_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-live")
        monkeypatch.setenv("GROQ_API_KEY", "gsk-groq-live")
        from app.ask_sonar.runtime import configure_answer_provider_from_env

        configure_answer_provider_from_env()
        provider = get_answer_provider()
        assert provider is not None
        assert provider.api_key == "sk-openai-live"

    def test_single_key_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.ask_sonar.runtime import (
            configure_answer_provider_from_env,
            get_answer_provider,
        )

        monkeypatch.setenv("ASK_SONAR_PROVIDER", "openai")
        monkeypatch.setenv("ASK_SONAR_BASE_URL", "https://api.groq.com/openai/v1")
        monkeypatch.setenv("GROQ_API_KEY", "gsk-only")
        configure_answer_provider_from_env()
        provider = get_answer_provider()
        assert provider is not None
        assert provider.api_key == "gsk-only"


class TestSharedRateLimit:
    """The SQL-backed limiter must enforce limits across simulated workers."""

    @pytest.fixture()
    def sqlite_engine(self, monkeypatch: pytest.MonkeyPatch):
        from sqlalchemy import create_engine

        import app.security.rate_limit as rate_limit_module
        from app.persistence.schema import metadata, rate_limit_hits

        engine = create_engine("sqlite:///:memory:")
        metadata.create_all(engine, tables=[rate_limit_hits])
        monkeypatch.setattr(rate_limit_module, "_sql_engine", lambda: engine)
        yield engine
        engine.dispose()

    def test_sql_path_enforces_limit(self, sqlite_engine) -> None:
        from app.security.rate_limit import check_rate_limit, reset_rate_limits

        reset_rate_limits()
        request = _request_for_ip("10.9.9.9")
        for _ in range(2):
            check_rate_limit(request, limit=2, window_seconds=60)
        with pytest.raises(HTTPException) as excinfo:
            check_rate_limit(request, limit=2, window_seconds=60)
        assert excinfo.value.status_code == 429

    def test_sql_path_is_shared_across_workers(self, sqlite_engine) -> None:
        # Two "workers" = two connections against the same engine: hits from
        # one must count against the other's limit.
        from sqlalchemy import func, select

        from app.persistence.schema import rate_limit_hits
        from app.security.rate_limit import check_rate_limit, reset_rate_limits

        reset_rate_limits()
        request = _request_for_ip("10.9.9.10")
        check_rate_limit(request, limit=3, window_seconds=60)  # worker A
        with sqlite_engine.connect() as conn:  # worker B observes worker A's hit
            count = conn.execute(select(func.count()).select_from(rate_limit_hits)).scalar()
        assert count == 1

    def test_sql_failure_degrades_to_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.security.rate_limit as rate_limit_module
        from app.security.rate_limit import check_rate_limit, reset_rate_limits

        class BrokenEngine:
            def begin(self):
                raise RuntimeError("db is down")

        monkeypatch.setattr(rate_limit_module, "_sql_engine", lambda: BrokenEngine())
        reset_rate_limits()
        try:
            request = _request_for_ip("10.9.9.11")
            check_rate_limit(request, limit=1, window_seconds=60)
            with pytest.raises(HTTPException) as excinfo:
                check_rate_limit(request, limit=1, window_seconds=60)
            assert excinfo.value.status_code == 429
        finally:
            reset_rate_limits()

    def test_sql_window_expiry(self, sqlite_engine) -> None:
        import time

        import app.security.rate_limit as rate_limit_module
        from app.security.rate_limit import check_rate_limit, reset_rate_limits

        real_time = time.time
        now = [real_time()]
        monkeypatch_time = rate_limit_module.time
        monkeypatch_time.time = lambda: now[0]
        reset_rate_limits()
        try:
            request = _request_for_ip("10.9.9.12")
            check_rate_limit(request, limit=1, window_seconds=60)
            with pytest.raises(HTTPException):
                check_rate_limit(request, limit=1, window_seconds=60)
            now[0] += 61  # window expires
            check_rate_limit(request, limit=1, window_seconds=60)  # allowed again
        finally:
            monkeypatch_time.time = real_time
            reset_rate_limits()


# ---------------------------------------------------------------------------
# H2b: legacy ownerless-scan access policy (2026-09-30 follow-up)
#
# Ownerless scans (anonymous / pre-ownership records) are no longer
# enumerable: they are excluded from every listing endpoint and reachable
# only by direct scan-id lookup (the unguessable scan id is a bearer
# capability). A signed-in user holding the scan id may claim an ownerless
# scan, which restores listing visibility under their ownership.
# ---------------------------------------------------------------------------


def _scan_record(
    scan_id: str,
    owner: str | None,
    repository_id: str = "repo-x",
    scanned_at: str = "2026-09-30T00:00:00+00:00",
):
    from app.history import build_scan_record
    from app.scoring.engine import calculate_score

    return build_scan_record(
        repository_id=repository_id,
        repository_path=f"/tmp/{repository_id}",
        findings=[],
        scoring=calculate_score([]),
        scan_id=scan_id,
        scanned_at=scanned_at,
        owner_user_id=owner,
    )


class TestVisibleScans:
    def test_ownerless_never_listed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.security.ownership import visible_scans

        monkeypatch.setattr(oauth_module, "current_user", lambda r: SimpleNamespace(id="a"))
        records = [_owned_record("a"), _owned_record(None), _owned_record("b")]
        visible = visible_scans(records, SimpleNamespace())  # type: ignore[arg-type]
        assert [r.scan_id for r in visible] == ["scan-1"]
        assert len(visible) == 1

    def test_anonymous_lists_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.security.ownership import visible_scans

        monkeypatch.setattr(oauth_module, "current_user", lambda r: None)
        records = [_owned_record("a"), _owned_record(None)]
        assert visible_scans(records, SimpleNamespace()) == []  # type: ignore[arg-type]


class TestOwnerlessStoreUpdate:
    def test_inmemory_update_owner(self) -> None:
        from app.history import InMemoryHistoryStore

        store = InMemoryHistoryStore()
        store.append(_scan_record("s1", None))
        assert store.update_owner("s1", "user-a") is True
        assert store.get("s1").owner_user_id == "user-a"
        assert store.update_owner("missing", "user-a") is False

    def test_jsonl_update_owner_roundtrip(self, tmp_path: Path) -> None:
        from app.history import JsonlHistoryStore

        store = JsonlHistoryStore(tmp_path / "history.jsonl")
        store.append(_scan_record("s1", None))
        store.append(_scan_record("s2", "user-b"))
        assert store.update_owner("s1", "user-a") is True
        assert store.get("s1").owner_user_id == "user-a"
        # Untouched record and file integrity survive the rewrite.
        assert store.get("s2").owner_user_id == "user-b"
        assert len(store.load_all()) == 2
        assert store.update_owner("missing", "user-a") is False


class TestOwnerlessListingPolicy:
    """End-to-end: listings hide other users' and ownerless scans."""

    @pytest.fixture
    def two_users(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
        from app.oauth import OAuthUserStore, new_session_token, set_oauth_user_store

        secret = "test-secret-" + "x" * 32
        monkeypatch.setenv("SONAR_SESSION_SECRET", secret)
        monkeypatch.setattr(oauth_module, "_secret_warning_emitted", True)
        store = OAuthUserStore(path=tmp_path / "oauth-users.json")
        previous = oauth_module.get_oauth_user_store()
        set_oauth_user_store(store)
        cookies: dict[str, str] = {}
        user_ids: dict[str, str] = {}
        for provider_id in ("1001", "1002"):
            user = store.upsert(
                provider="github",
                provider_user_id=provider_id,
                name=f"User {provider_id}",
                email=f"{provider_id}@example.com",
                avatar_url="",
            )
            cookies[provider_id] = f"sonar_session={new_session_token(user.id, secret)}"
            user_ids[provider_id] = user.id
        yield {"cookies": cookies, "user_ids": user_ids}
        set_oauth_user_store(previous)

    @pytest.fixture
    def seeded_store(self, tmp_path: Path, two_users: dict):
        import app.main as main_module
        from app.history import JsonlHistoryStore
        from app.history.repository_identity import compute_repository_id

        repo_dir = tmp_path / "repo-x"
        repo_dir.mkdir()
        repository_id = compute_repository_id(repo_dir)
        store = JsonlHistoryStore(tmp_path / "history.jsonl")
        previous = main_module.get_history_store()
        main_module.set_history_store(store)
        uid_a = two_users["user_ids"]["1001"]
        store.append(
            _scan_record(
                "owned-by-a",
                uid_a,
                repository_id=repository_id,
                scanned_at="2026-09-30T00:00:01+00:00",
            )
        )
        store.append(
            _scan_record(
                "ownerless",
                None,
                repository_id=repository_id,
                scanned_at="2026-09-30T00:00:02+00:00",
            )
        )
        yield {"repo_dir": str(repo_dir)}
        main_module.set_history_store(previous)

    def test_list_hides_ownerless_and_other_users(self, two_users: dict, seeded_store) -> None:
        import app.main as main_module

        client = TestClient(main_module.app, raise_server_exceptions=False)
        cookies = two_users["cookies"]

        listed_a = client.get("/api/history/list", headers={"Cookie": cookies["1001"]}).json()[
            "scans"
        ]
        assert [s["scan_id"] for s in listed_a] == ["owned-by-a"]

        # The other user sees an empty list — not even the ownerless scan.
        listed_b = client.get("/api/history/list", headers={"Cookie": cookies["1002"]}).json()[
            "scans"
        ]
        assert listed_b == []

    def test_ownerless_fetchable_by_scan_id_capability(self, two_users: dict, seeded_store) -> None:
        import app.main as main_module

        client = TestClient(main_module.app, raise_server_exceptions=False)
        cookies = two_users["cookies"]
        # The bearer capability (unguessable scan id) still works for anyone.
        ok = client.get("/api/history/ownerless", headers={"Cookie": cookies["1002"]})
        assert ok.status_code == 200
        anon = client.get("/api/history/ownerless")
        assert anon.status_code == 200

    def test_latest_returns_only_visible(self, two_users: dict, seeded_store) -> None:
        import app.main as main_module

        client = TestClient(main_module.app, raise_server_exceptions=False)
        cookies = two_users["cookies"]
        # The newest record overall is ownerless; user A gets their own latest.
        latest = client.get(
            "/api/history/latest",
            params={"repo_path": seeded_store["repo_dir"]},
            headers={"Cookie": cookies["1001"]},
        )
        assert latest.status_code == 200
        assert latest.json()["scan_id"] == "owned-by-a"
        # User B has no visible scans -> 404.
        denied = client.get(
            "/api/history/latest",
            params={"repo_path": seeded_store["repo_dir"]},
            headers={"Cookie": cookies["1002"]},
        )
        assert denied.status_code == 404

    def test_claim_ownerless_scan(self, two_users: dict, seeded_store) -> None:
        import app.main as main_module

        client = TestClient(main_module.app, raise_server_exceptions=False)
        cookies = two_users["cookies"]

        # Anonymous callers cannot claim.
        anon = client.post("/api/history/ownerless/claim")
        assert anon.status_code == 401

        # User B claims the ownerless scan with its scan id.
        claimed = client.post("/api/history/ownerless/claim", headers={"Cookie": cookies["1002"]})
        assert claimed.status_code == 200
        assert claimed.json() == {
            "scan_id": "ownerless",
            "owner_user_id": two_users["user_ids"]["1002"],
            "claimed": True,
        }

        # It now appears in user B's listing, and is hidden from user A.
        listed_b = client.get("/api/history/list", headers={"Cookie": cookies["1002"]}).json()[
            "scans"
        ]
        assert [s["scan_id"] for s in listed_b] == ["ownerless"]
        assert (
            client.get("/api/history/ownerless", headers={"Cookie": cookies["1001"]}).status_code
            == 404
        )

        # Re-claiming your own scan is idempotent.
        again = client.post("/api/history/ownerless/claim", headers={"Cookie": cookies["1002"]})
        assert again.json()["claimed"] is False

        # Claiming someone else's owned scan is rejected.
        conflict = client.post("/api/history/owned-by-a/claim", headers={"Cookie": cookies["1002"]})
        assert conflict.status_code == 409

        # Unknown scan id 404s.
        missing = client.post("/api/history/nope/claim", headers={"Cookie": cookies["1002"]})
        assert missing.status_code == 404


class TestSharedRateLimitConcurrency:
    """Genuine thread-level race: N workers hammer one bucket at once."""

    def test_sql_concurrent_workers_never_over_admit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        from sqlalchemy import create_engine, func, select
        from sqlalchemy.pool import NullPool

        import app.security.rate_limit as rate_limit_module
        from app.persistence.schema import metadata, rate_limit_hits
        from app.security.rate_limit import check_rate_limit, reset_rate_limits

        # File-backed SQLite so each thread gets its own real connection
        # (``:memory:`` would share one connection and prove nothing).
        engine = create_engine(
            f"sqlite:///{tmp_path / 'ratelimit.db'}",
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=NullPool,
        )
        metadata.create_all(engine, tables=[rate_limit_hits])
        monkeypatch.setattr(rate_limit_module, "_sql_engine", lambda: engine)
        reset_rate_limits()

        workers = 20
        limit = 5
        barrier = threading.Barrier(workers)
        state_lock = threading.Lock()
        admitted: list[int] = []
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                barrier.wait(timeout=30)  # release every thread at once
                request = _request_for_ip("10.9.9.99")
                try:
                    check_rate_limit(request, limit=limit, window_seconds=60)
                except HTTPException as exc:
                    assert exc.status_code == 429
                else:
                    with state_lock:
                        admitted.append(index)
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                with state_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            assert not errors, f"worker errors: {errors!r}"
            assert not any(thread.is_alive() for thread in threads), "worker hung"
            # Exactly `limit` admissions: no over-admission under contention.
            assert len(admitted) == limit
            with engine.connect() as conn:
                stored = conn.execute(select(func.count()).select_from(rate_limit_hits)).scalar()
            assert stored == limit
        finally:
            reset_rate_limits()
            engine.dispose()


class TestAlembicRevisionCheck:
    """Startup must accept the DB when it is at the shipped Alembic head.

    Regression: shipping migrations 0006/0007 without updating the startup
    revision check crashed production startup with "Database schema is not at
    required Alembic revision". The pin lives in
    ``app.persistence.runtime.REQUIRED_ALEMBIC_REVISION`` and
    ``TestAlembicRevisionPinConsistency`` fails in CI if it drifts from the
    migration scripts, so the desync can never reach production again.
    """

    def _fake_engine(self, version_num: str | None):
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:")

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, statement):
                class Result:
                    def scalar_one_or_none(self):
                        return version_num

                return Result()

        engine.connect = lambda: FakeConnection()  # type: ignore[method-assign]
        return engine

    def _pg_config(self):
        from pathlib import Path

        from app.persistence.config import PersistenceConfig

        return PersistenceConfig(
            database_url="postgresql://user:pass@localhost:5432/db",
            data_root=Path("/tmp"),
        )

    def test_accepts_database_at_shipped_head(self) -> None:
        from app.persistence.runtime import REQUIRED_ALEMBIC_REVISION, _initialize_schema

        assert REQUIRED_ALEMBIC_REVISION == "20261006_0008"
        # Must not raise: the DB was migrated to the shipped head.
        _initialize_schema(self._fake_engine(REQUIRED_ALEMBIC_REVISION), self._pg_config())

    def test_rejects_stale_database(self) -> None:
        import pytest

        from app.persistence.runtime import _initialize_schema

        with pytest.raises(RuntimeError, match="Alembic revision"):
            _initialize_schema(self._fake_engine("20260927_0005"), self._pg_config())


class TestAlembicRevisionPinConsistency:
    """The startup pin must match the actual head of the migration scripts."""

    def test_pin_matches_migration_head(self) -> None:
        from pathlib import Path

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        from app.persistence.runtime import REQUIRED_ALEMBIC_REVISION

        script_location = Path(__file__).resolve().parents[2] / "alembic"
        assert (script_location / "versions").is_dir(), script_location
        config = Config()
        config.set_main_option("script_location", str(script_location))
        head = ScriptDirectory.from_config(config).get_current_head()
        assert head == REQUIRED_ALEMBIC_REVISION, (
            f"REQUIRED_ALEMBIC_REVISION={REQUIRED_ALEMBIC_REVISION!r} "
            f"but migration head is {head!r}: bump the pin when shipping a migration"
        )
