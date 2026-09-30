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
