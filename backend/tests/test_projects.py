"""Unit tests for the ``app.projects`` domain layer.

``tests/api/test_projects_api.py`` covers the project HTTP surface (list
privacy, unknown-project 404, legacy connect rejection) and
``tests/security/test_tenant_isolation.py`` covers cross-tenant endpoint
isolation. This module covers the rest: the ``ProjectRecord`` public
contract, ``ProjectStore`` persistence/upsert/dedupe/scan recording,
remote URL normalization, project id generation, the ``_git`` helper,
``connect_github_project`` branching, request-model validation, and the
store accessors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.projects import (
    GitHubProjectConnectRequest,
    ManagedGitHubConnectRequest,
    ProjectRecord,
    ProjectStore,
    _git,
    _normalize_remote,
    _project_id,
    connect_github_project,
    get_project_store,
    set_project_store,
)
from app.security.tenant import bind_tenant, reset_tenant

import app.projects as projects


def _record(project_id: str = "proj_1", **overrides: Any) -> ProjectRecord:
    base = {
        "project_id": project_id,
        "provider": "github",
        "owner": "acme",
        "name": "service",
        "default_branch": "main",
        "connected_at": "2026-09-28T00:00:00+00:00",
        "local_checkout_path": "/tmp/svc",
    }
    base.update(overrides)
    return ProjectRecord(**base)


def _store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "projects.json")


def _connect_request(path: str) -> GitHubProjectConnectRequest:
    return GitHubProjectConnectRequest(
        owner="acme",
        name="service",
        local_checkout_path=path,
    )


def _fake_git(
    mapping: dict[tuple[str, ...], str],
    failures: frozenset[tuple[str, ...]] = frozenset(),
) -> Callable[..., str]:
    def _run(repo: Path, *args: str) -> str:
        key = tuple(args)
        if key in failures:
            raise ValueError(f"git {' '.join(key)} failed")
        return mapping[key]

    return _run


def test_to_public_dict_contract() -> None:
    public = _record().to_public_dict()
    assert public["project_id"] == "proj_1"
    assert public["full_name"] == "acme/service"
    assert public["provider"] == "github"
    assert public["owner"] == "acme"
    assert public["name"] == "service"
    assert public["default_branch"] == "main"
    assert public["connected_at"] == "2026-09-28T00:00:00+00:00"
    assert "local_checkout_path" not in public


def test_to_public_dict_excludes_internal_fields() -> None:
    public = _record().to_public_dict()
    assert "tenant_id" not in public
    assert set(public) == {
        "project_id",
        "provider",
        "owner",
        "name",
        "full_name",
        "default_branch",
        "connected_at",
        "latest_scan_id",
        "latest_score",
        "provider_repository_id",
        "provider_installation_id",
    }


def test_record_optional_fields_default_to_none() -> None:
    record = _record()
    assert record.latest_scan_id is None
    assert record.latest_score is None
    assert record.provider_repository_id is None
    assert record.provider_installation_id is None


def test_store_returns_empty_list_when_file_missing(tmp_path: Path) -> None:
    assert _store(tmp_path).list() == []
    assert _store(tmp_path).get("proj_missing") is None


def test_store_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    ProjectStore(path).upsert(_record("proj_persist"))
    fetched = ProjectStore(path).get("proj_persist")
    assert fetched is not None
    assert fetched.project_id == "proj_persist"
    assert fetched.local_checkout_path == "/tmp/svc"
    assert path.exists()


def test_upsert_replaces_same_project_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_record("proj_dup"))
    store.upsert(_record("proj_dup", default_branch="develop"))
    records = store.list()
    assert len(records) == 1
    assert records[0].default_branch == "develop"
    assert records[0].project_id == "proj_dup"


def test_upsert_reassigns_record_from_foreign_tenant(tmp_path: Path) -> None:
    store = _store(tmp_path)
    returned = store.upsert(_record("proj_foreign", tenant_id="tenant-b"))
    assert returned.tenant_id == "local"
    assert store.get("proj_foreign").tenant_id == "local"


def test_upsert_sorts_records_by_project_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_record("proj_b"))
    store.upsert(_record("proj_a"))
    records = store.list()
    assert records[0].project_id == "proj_a"
    assert records[1].project_id == "proj_b"


def test_record_scan_updates_scan_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_record("proj_scan"))
    updated = store.record_scan("proj_scan", scan_id="scan_9", score=87)
    assert updated.latest_scan_id == "scan_9"
    assert updated.latest_score == 87
    assert updated.project_id == "proj_scan"
    assert _store(tmp_path).get("proj_scan").latest_score == 87


def test_record_scan_missing_project_raises(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="Project not found"):
        _store(tmp_path).record_scan("proj_missing", scan_id="scan_1", score=50)


def test_list_hides_records_from_other_tenants(tmp_path: Path) -> None:
    store = _store(tmp_path)
    token = bind_tenant("tenant-b")
    store.upsert(_record("proj_tenant_b"))
    reset_tenant(token)
    store.upsert(_record("proj_local"))
    visible = store.list()
    assert len(visible) == 1
    assert visible[0].project_id == "proj_local"


def test_get_ignores_record_from_other_tenant(tmp_path: Path) -> None:
    store = _store(tmp_path)
    token = bind_tenant("tenant-b")
    store.upsert(_record("proj_other"))
    reset_tenant(token)
    assert store.get("proj_other") is None


def test_normalize_remote_https_url() -> None:
    assert _normalize_remote("https://github.com/acme/service.git") == "acme/service"


def test_normalize_remote_http_url() -> None:
    assert _normalize_remote("http://github.com/acme/service") == "acme/service"


def test_normalize_remote_git_ssh_url() -> None:
    assert _normalize_remote("git@github.com:acme/service.git") == "acme/service"


def test_normalize_remote_ssh_url() -> None:
    assert _normalize_remote("ssh://git@github.com/acme/service.git") == "acme/service"


def test_normalize_remote_lowercases_and_trims() -> None:
    assert _normalize_remote("  https://github.com/ACME/Service.git  ") == "acme/service"


def test_normalize_remote_only_strips_lowercase_git_suffix() -> None:
    assert _normalize_remote("https://github.com/acme/service.GIT") == "acme/service.git"


def test_normalize_remote_rejects_non_github() -> None:
    with pytest.raises(ValueError, match="not a GitHub remote"):
        _normalize_remote("https://gitlab.com/acme/service.git")


def test_normalize_remote_rejects_empty() -> None:
    with pytest.raises(ValueError, match="not a GitHub remote"):
        _normalize_remote("")


def test_project_id_is_deterministic_and_case_insensitive() -> None:
    first = _project_id("Acme/Service")
    second = _project_id("acme/service")
    assert first == second
    assert first.startswith("proj_")
    assert len(first) == len("proj_") + 20


def test_project_id_differs_per_repository() -> None:
    assert _project_id("acme/service") != _project_id("acme/other")


def test_git_raises_value_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Completed:
        returncode = 1
        stdout = ""
        stderr = "fatal: boom"

    monkeypatch.setattr(
        "app.projects.subprocess.run", lambda *args, **kwargs: _Completed()
    )
    with pytest.raises(ValueError, match="boom"):
        _git(Path("/tmp"), "rev-parse", "--show-toplevel")


def test_git_returns_stripped_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Completed:
        returncode = 0
        stdout = "  main\n"
        stderr = ""

    monkeypatch.setattr(
        "app.projects.subprocess.run", lambda *args, **kwargs: _Completed()
    )
    assert _git(Path("/tmp"), "branch", "--show-current") == "main"


def test_connect_github_project_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = tmp_path / "svc"
    top.mkdir()
    monkeypatch.setattr(
        "app.projects._git",
        _fake_git({
            ("rev-parse", "--show-toplevel"): str(top),
            ("remote", "get-url", "origin"): "git@github.com:acme/service.git",
            ("symbolic-ref", "refs/remotes/origin/HEAD"): "refs/remotes/origin/main",
        }),
    )
    record = connect_github_project(_connect_request(str(top)))
    assert record.default_branch == "main"
    assert record.local_checkout_path == str(top)
    assert record.provider == "github"
    assert record.owner == "acme"
    assert record.name == "service"


def test_connect_github_project_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        connect_github_project(_connect_request(str(tmp_path / "missing")))


def test_connect_github_project_rejects_origin_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = tmp_path / "svc"
    top.mkdir()
    monkeypatch.setattr(
        "app.projects._git",
        _fake_git({
            ("rev-parse", "--show-toplevel"): str(top),
            ("remote", "get-url", "origin"): "https://github.com/other/repo.git",
        }),
    )
    with pytest.raises(ValueError, match="does not match"):
        connect_github_project(_connect_request(str(top)))


def test_connect_github_project_falls_back_to_current_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = tmp_path / "svc"
    top.mkdir()
    monkeypatch.setattr(
        "app.projects._git",
        _fake_git(
            {
                ("rev-parse", "--show-toplevel"): str(top),
                ("remote", "get-url", "origin"): "https://github.com/acme/service.git",
                ("branch", "--show-current"): "dev",
            },
            failures=frozenset({("symbolic-ref", "refs/remotes/origin/HEAD")}),
        ),
    )
    record = connect_github_project(_connect_request(str(top)))
    assert record.default_branch == "dev"


def test_connect_github_project_defaults_to_main_when_branch_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = tmp_path / "svc"
    top.mkdir()
    monkeypatch.setattr(
        "app.projects._git",
        _fake_git(
            {
                ("rev-parse", "--show-toplevel"): str(top),
                ("remote", "get-url", "origin"): "https://github.com/acme/service.git",
                ("branch", "--show-current"): "",
            },
            failures=frozenset({("symbolic-ref", "refs/remotes/origin/HEAD")}),
        ),
    )
    record = connect_github_project(_connect_request(str(top)))
    assert record.default_branch == "main"


def test_connect_request_rejects_blank_owner() -> None:
    with pytest.raises(ValidationError):
        GitHubProjectConnectRequest(owner="", name="service", local_checkout_path="/tmp")


def test_connect_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        GitHubProjectConnectRequest(owner="acme", name="", local_checkout_path="/tmp")


def test_connect_request_rejects_overlong_name() -> None:
    with pytest.raises(ValidationError):
        GitHubProjectConnectRequest(
            owner="acme", name="x" * 101, local_checkout_path="/tmp"
        )


def test_managed_connect_request_rejects_short_full_name() -> None:
    with pytest.raises(ValidationError):
        ManagedGitHubConnectRequest(repository_full_name="ab")


def test_managed_connect_request_accepts_full_name() -> None:
    request = ManagedGitHubConnectRequest(repository_full_name="acme/service")
    assert request.repository_full_name == "acme/service"


def test_get_project_endpoint_returns_public_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_record("proj_api"))
    set_project_store(store)
    response = TestClient(app).get("/api/projects/proj_api")
    assert response.status_code == 200
    body = response.json()["project"]
    assert body["project_id"] == "proj_api"
    assert body["full_name"] == "acme/service"
    assert "local_checkout_path" not in body


def test_project_list_endpoint_count_contract(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_record("proj_1"))
    store.upsert(_record("proj_2"))
    set_project_store(store)
    response = TestClient(app).get("/api/projects")
    payload = response.json()
    assert response.status_code == 200
    assert payload["count"] == 2
    assert len(payload["projects"]) == 2


def test_store_accessors_round_trip(tmp_path: Path) -> None:
    previous = get_project_store()
    custom = _store(tmp_path)
    set_project_store(custom)
    assert get_project_store() is custom
    set_project_store(previous)
    assert get_project_store() is previous
