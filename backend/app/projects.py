"""Persistent project/repository connections for Code Sonar."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.github_integration import GitHubIntegration, get_github_integration


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    project_id: str
    provider: str
    owner: str
    name: str
    default_branch: str
    connected_at: str
    local_checkout_path: str
    latest_scan_id: str | None = None
    latest_score: int | None = None
    provider_installation_id: int | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "provider": self.provider,
            "owner": self.owner,
            "name": self.name,
            "full_name": f"{self.owner}/{self.name}",
            "default_branch": self.default_branch,
            "connected_at": self.connected_at,
            "latest_scan_id": self.latest_scan_id,
            "latest_score": self.latest_score,
            "provider_installation_id": self.provider_installation_id,
        }


class ProjectStore:
    """Small JSON-backed registry. Local checkout paths never leave the server."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "projects.json")
        self._lock = RLock()

    def _load(self) -> list[ProjectRecord]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [ProjectRecord(**item) for item in data]

    def _save(self, records: list[ProjectRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([asdict(record) for record in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def list(self) -> list[ProjectRecord]:
        with self._lock:
            return self._load()

    def get(self, project_id: str) -> ProjectRecord | None:
        with self._lock:
            return next((item for item in self._load() if item.project_id == project_id), None)

    def find_by_full_name(self, full_name: str) -> ProjectRecord | None:
        normalized = full_name.strip().lower()
        with self._lock:
            return next(
                (
                    item
                    for item in self._load()
                    if f"{item.owner}/{item.name}".lower() == normalized
                ),
                None,
            )

    def upsert(self, record: ProjectRecord) -> ProjectRecord:
        with self._lock:
            records = [item for item in self._load() if item.project_id != record.project_id]
            records.append(record)
            records.sort(key=lambda item: item.project_id)
            self._save(records)
        return record

    def record_scan(self, project_id: str, *, scan_id: str, score: int) -> ProjectRecord:
        with self._lock:
            records = self._load()
            current = next((item for item in records if item.project_id == project_id), None)
            if current is None:
                raise LookupError("Project not found")
            updated = replace(current, latest_scan_id=scan_id, latest_score=score)
            records = [updated if item.project_id == project_id else item for item in records]
            self._save(records)
            return updated

    def bind_installation(self, project_id: str, installation_id: int) -> ProjectRecord:
        with self._lock:
            records = self._load()
            current = next((item for item in records if item.project_id == project_id), None)
            if current is None:
                raise LookupError("Project not found")
            updated = replace(current, provider_installation_id=installation_id)
            self._save([updated if item.project_id == project_id else item for item in records])
            return updated


class GitHubProjectConnectRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    local_checkout_path: str = Field(min_length=1)


class ManagedGitHubConnectRequest(BaseModel):
    repository_full_name: str = Field(min_length=3, max_length=220)
    installation_id: int | None = Field(default=None, ge=1)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "Git command failed")
    return completed.stdout.strip()


def _normalize_remote(remote: str) -> str:
    value = remote.strip().removesuffix(".git").lower()
    if value.startswith("git@github.com:"):
        return value.removeprefix("git@github.com:")
    for prefix in ("https://github.com/", "http://github.com/", "ssh://git@github.com/"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    raise ValueError("Repository origin is not a GitHub remote")


def _project_id(full_name: str) -> str:
    return "proj_" + hashlib.sha256(f"github:{full_name.lower()}".encode()).hexdigest()[:20]


def connect_github_project(request: GitHubProjectConnectRequest) -> ProjectRecord:
    repo = Path(request.local_checkout_path).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise ValueError("Local checkout path does not exist or is not a directory")

    top_level = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    remote = _normalize_remote(_git(top_level, "remote", "get-url", "origin"))
    expected = f"{request.owner}/{request.name}".lower()
    if remote != expected:
        raise ValueError("Local checkout origin does not match the requested GitHub repository")

    try:
        default_ref = _git(top_level, "symbolic-ref", "refs/remotes/origin/HEAD")
        default_branch = default_ref.rsplit("/", 1)[-1]
    except ValueError:
        default_branch = _git(top_level, "branch", "--show-current") or "main"

    return ProjectRecord(
        project_id=_project_id(expected),
        provider="github",
        owner=request.owner,
        name=request.name,
        default_branch=default_branch,
        connected_at=datetime.now(timezone.utc).isoformat(),
        local_checkout_path=str(top_level),
    )


def _resolve_github_integration(
    installation_id: int | None,
) -> tuple[GitHubIntegration, int | None]:
    from app.github_app import get_github_app_runtime

    runtime = get_github_app_runtime()
    installations = runtime.installations.list() if runtime.configured else []
    if installations:
        selected_id = installation_id or installations[0].installation_id
        if runtime.installations.get(selected_id) is None:
            raise LookupError("GitHub App installation is not registered")
        return runtime.integration_for_installation(selected_id), selected_id

    integration = get_github_integration()
    if not integration.configured:
        raise PermissionError("GitHub integration is not configured")
    return integration, None


_store = ProjectStore()
router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_project_store() -> ProjectStore:
    return _store


def set_project_store(store: ProjectStore) -> None:
    global _store
    _store = store


@router.get("")
async def list_projects() -> dict[str, Any]:
    projects = get_project_store().list()
    return {"count": len(projects), "projects": [item.to_public_dict() for item in projects]}


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    project = get_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.to_public_dict()}


@router.get("/connect/github/status")
async def github_connection_status() -> dict[str, Any]:
    from app.github_app import get_github_app_runtime

    runtime = get_github_app_runtime()
    installations = runtime.installations.list() if runtime.configured else []
    static_integration = get_github_integration()
    app_ready = runtime.configured and bool(installations)
    static_ready = static_integration.configured
    return {
        "configured": app_ready or static_ready,
        "auth_mode": "app" if app_ready else (static_integration.auth_mode if static_ready else None),
        "app_installable": runtime.configured,
        "installation_count": len(installations),
        "webhook_configured": runtime.settings.webhook_configured,
        "token_persisted": False,
        "token_exposed": False,
        "managed_checkout": True,
    }


@router.get("/connect/github/repositories")
async def github_repositories(
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    try:
        integration, selected_installation_id = _resolve_github_integration(installation_id)
        repositories = integration.list_repositories()
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="GitHub repository discovery failed") from exc
    return {
        "count": len(repositories),
        "repositories": [item.to_public_dict() for item in repositories],
        "installation_id": selected_installation_id,
        "token_exposed": False,
    }


@router.post("/connect/github/managed")
async def connect_managed_github(request: ManagedGitHubConnectRequest) -> dict[str, Any]:
    try:
        integration, selected_installation_id = _resolve_github_integration(
            request.installation_id
        )
        repository = integration.get_repository(request.repository_full_name)
        checkout = integration.prepare_checkout(repository)
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="GitHub repository checkout failed") from exc

    record = ProjectRecord(
        project_id=_project_id(repository.full_name),
        provider="github",
        owner=repository.owner,
        name=repository.name,
        default_branch=repository.default_branch,
        connected_at=datetime.now(timezone.utc).isoformat(),
        local_checkout_path=str(checkout),
        provider_installation_id=selected_installation_id,
    )
    get_project_store().upsert(record)
    return {
        "project": record.to_public_dict(),
        "connection_verified": True,
        "managed_checkout": True,
        "local_checkout_path_exposed": False,
        "token_persisted": False,
        "token_exposed": False,
    }


@router.post("/connect/github")
async def connect_github(request: GitHubProjectConnectRequest) -> dict[str, Any]:
    """Legacy local-checkout connector retained during GitHub App migration."""
    try:
        record = connect_github_project(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_project_store().upsert(record)
    return {
        "project": record.to_public_dict(),
        "connection_verified": True,
        "local_checkout_path_exposed": False,
    }
