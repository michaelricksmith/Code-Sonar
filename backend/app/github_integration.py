"""GitHub repository discovery and server-managed checkout support."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2026-03-10"


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    repository_id: int
    full_name: str
    owner: str
    name: str
    default_branch: str
    private: bool
    clone_url: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "full_name": self.full_name,
            "owner": self.owner,
            "name": self.name,
            "default_branch": self.default_branch,
            "private": self.private,
        }


class GitHubIntegration:
    """Read repository metadata and create managed checkouts without persisting tokens."""

    def __init__(
        self,
        *,
        token: str | None = None,
        auth_mode: str | None = None,
        checkout_root: Path | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("CODE_SONAR_GITHUB_TOKEN", "")
        self.auth_mode = (
            auth_mode if auth_mode is not None else os.getenv("CODE_SONAR_GITHUB_AUTH_MODE", "oauth")
        ).strip().lower()
        self.checkout_root = checkout_root or (Path.home() / ".code-sonar" / "repositories")
        self.client = client or httpx.Client(timeout=20.0)

    @property
    def configured(self) -> bool:
        return bool(self.token) and self.auth_mode in {"oauth", "app"}

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise PermissionError("GitHub integration is not configured")
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def list_repositories(self) -> list[GitHubRepository]:
        if self.auth_mode == "app":
            url = f"{_GITHUB_API}/installation/repositories"
            params = {"per_page": 100}
            response = self.client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("repositories", [])
        else:
            url = f"{_GITHUB_API}/user/repos"
            params = {
                "per_page": 100,
                "sort": "updated",
                "affiliation": "owner,collaborator,organization_member",
            }
            response = self.client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            items = response.json()

        repositories = [self._parse_repository(item) for item in items]
        repositories.sort(key=lambda item: item.full_name.lower())
        return repositories

    def get_repository(self, full_name: str) -> GitHubRepository:
        normalized = full_name.strip().strip("/")
        if normalized.count("/") != 1:
            raise ValueError("GitHub repository must use owner/name format")
        response = self.client.get(
            f"{_GITHUB_API}/repos/{normalized}",
            headers=self._headers(),
        )
        if response.status_code == 404:
            raise LookupError("GitHub repository is not accessible")
        response.raise_for_status()
        return self._parse_repository(response.json())

    def prepare_checkout(self, repository: GitHubRepository) -> Path:
        """Clone or fast-forward a repository into the server-managed checkout root."""
        destination = self.checkout_root / str(repository.repository_id)
        self.checkout_root.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            if not (destination / ".git").exists():
                raise FileExistsError("Managed checkout destination exists but is not a Git repository")
            self._git_authenticated(
                ["git", "-C", str(destination), "fetch", "--prune", "origin"],
                failure="Could not refresh managed GitHub checkout",
            )
            self._git_authenticated(
                [
                    "git",
                    "-C",
                    str(destination),
                    "reset",
                    "--hard",
                    f"origin/{repository.default_branch}",
                ],
                failure="Could not reset managed GitHub checkout",
            )
            return destination.resolve()

        temp_parent = Path(tempfile.mkdtemp(prefix="code-sonar-github-", dir=self.checkout_root))
        temp_checkout = temp_parent / "checkout"
        try:
            self._git_authenticated(
                [
                    "git",
                    "clone",
                    "--branch",
                    repository.default_branch,
                    "--single-branch",
                    repository.clone_url,
                    str(temp_checkout),
                ],
                failure="Could not clone GitHub repository",
            )
            temp_checkout.replace(destination)
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)
        return destination.resolve()

    def _git_authenticated(self, args: list[str], *, failure: str) -> None:
        if not self.configured:
            raise PermissionError("GitHub integration is not configured")
        with tempfile.TemporaryDirectory(prefix="code-sonar-askpass-") as temp_dir:
            askpass = Path(temp_dir) / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
                "  *) printf '%s\\n' \"$CODE_SONAR_GIT_TOKEN\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            env = os.environ.copy()
            env.update(
                {
                    "GIT_ASKPASS": str(askpass),
                    "GIT_TERMINAL_PROMPT": "0",
                    "CODE_SONAR_GIT_TOKEN": self.token,
                }
            )
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        if completed.returncode != 0:
            raise RuntimeError(failure)

    @staticmethod
    def _parse_repository(item: dict[str, Any]) -> GitHubRepository:
        full_name = str(item["full_name"])
        owner, name = full_name.split("/", 1)
        return GitHubRepository(
            repository_id=int(item["id"]),
            full_name=full_name,
            owner=owner,
            name=name,
            default_branch=str(item.get("default_branch") or "main"),
            private=bool(item.get("private", False)),
            clone_url=str(item.get("clone_url") or f"https://github.com/{full_name}.git"),
        )


_integration = GitHubIntegration()


def get_github_integration() -> GitHubIntegration:
    return _integration


def set_github_integration(integration: GitHubIntegration) -> None:
    global _integration
    _integration = integration
