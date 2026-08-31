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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


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


class GitHubProjectConnectRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    local_checkout_path: str = Field(min_length=1)


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

    project_id = "proj_" + hashlib.sha256(f"github:{expected}".encode()).hexdigest()[:20]
    return ProjectRecord(
        project_id=project_id,
        provider="github",
        owner=request.owner,
        name=request.name,
        default_branch=default_branch,
        connected_at=datetime.now(timezone.utc).isoformat(),
        local_checkout_path=str(top_level),
    )


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


@router.post("/connect/github")
async def connect_github(request: GitHubProjectConnectRequest) -> dict[str, Any]:
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
