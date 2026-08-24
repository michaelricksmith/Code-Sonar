"""GitHub repository provider implementation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime
from typing import Any

import httpx

from app.providers.base import (
    CloneResult,
    ProviderBranch,
    ProviderRegistry,
    ProviderRepository,
    ProviderUser,
    RepositoryProvider,
    get_provider_registry,
)


class GitHubProvider(RepositoryProvider):
    """GitHub.com and GitHub Enterprise repository provider."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str = "https://api.github.com",
        web_base_url: str = "https://github.com",
    ) -> None:
        self._client_id = client_id or os.environ.get("GITHUB_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get("GITHUB_CLIENT_SECRET", "")
        self._base_url = base_url.rstrip("/")
        self._web_base_url = web_base_url.rstrip("/")
        self._api_version = "2022-11-28"

    @property
    def provider_type(self) -> str:
        return "github"

    @property
    def display_name(self) -> str:
        return "GitHub"

    @property
    def required_scopes(self) -> list[str]:
        # Minimum scopes for repository access
        return ["repo", "read:user", "read:org"]

    def get_authorization_url(
        self,
        client_id: str,
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Generate GitHub OAuth authorization URL."""
        scope_str = " ".join(scopes or self.required_scopes)
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope_str,
            "state": state,
            "allow_signup": "true",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self._web_base_url}/login/oauth/authorize?{query}"

    async def exchange_code_for_tokens(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code: str,
    ) -> dict[str, Any]:
        """Exchange authorization code for access token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._web_base_url}/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={
                    "Accept": "application/json",
                    "X-GitHub-Api-Version": self._api_version,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise ValueError(f"GitHub OAuth error: {data.get('error_description', data['error'])}")

            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "scope": data.get("scope"),
                "token_type": data.get("token_type", "bearer"),
            }

    async def refresh_access_token(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> dict[str, Any]:
        """Refresh an expired access token (GitHub uses long-lived tokens, refresh may not be needed)."""
        # GitHub OAuth tokens don't typically expire, but GitHub Apps tokens do
        # For OAuth Apps, we just return the same token
        # For GitHub Apps, we'd need a different implementation
        return {
            "access_token": refresh_token,  # GitHub OAuth tokens are long-lived
            "refresh_token": refresh_token,
            "expires_in": None,
        }

    def _get_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
            "User-Agent": "Code Sonar",
        }

    async def get_authenticated_user(
        self,
        access_token: str,
    ) -> ProviderUser:
        """Get the authenticated GitHub user."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/user",
                headers=self._get_headers(access_token),
                timeout=30.0,
            )
            response.raise_for_status()
            user_data = response.json()

            return ProviderUser(
                provider_user_id=str(user_data["id"]),
                username=user_data["login"],
                display_name=user_data.get("name"),
                email=user_data.get("email"),
                avatar_url=user_data.get("avatar_url"),
                metadata=user_data,
            )

    async def list_repositories(
        self,
        access_token: str,
        page: int = 1,
        per_page: int = 100,
        visibility: str | None = None,
        affiliation: str | None = None,
    ) -> list[ProviderRepository]:
        """List repositories accessible to the authenticated user."""
        params: dict[str, Any] = {
            "page": page,
            "per_page": min(per_page, 100),
            "sort": "updated",
            "direction": "desc",
        }
        if visibility:
            params["visibility"] = visibility
        if affiliation:
            params["affiliation"] = affiliation

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/user/repos",
                headers=self._get_headers(access_token),
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            repos_data = response.json()

        return [self._normalize_repository(r) for r in repos_data]

    async def get_repository(
        self,
        access_token: str,
        owner: str,
        repo: str,
    ) -> ProviderRepository | None:
        """Get a specific repository by owner and name."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}",
                headers=self._get_headers(access_token),
                timeout=30.0,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            repo_data = response.json()
            return self._normalize_repository(repo_data)

    async def list_branches(
        self,
        access_token: str,
        owner: str,
        repo: str,
        page: int = 1,
        per_page: int = 100,
    ) -> list[ProviderBranch]:
        """List branches for a repository."""
        params = {
            "page": page,
            "per_page": min(per_page, 100),
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/branches",
                headers=self._get_headers(access_token),
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            branches_data = response.json()

        return [self._normalize_branch(b) for b in branches_data]

    async def get_branch(
        self,
        access_token: str,
        owner: str,
        repo: str,
        branch: str,
    ) -> ProviderBranch | None:
        """Get a specific branch."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/branches/{branch}",
                headers=self._get_headers(access_token),
                timeout=30.0,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            branch_data = response.json()
            return self._normalize_branch(branch_data)

    async def clone_repository(
        self,
        access_token: str,
        owner: str,
        repo: str,
        branch: str,
        target_path: str,
    ) -> CloneResult:
        """Clone a repository using the access token for authentication."""
        # Use GitHub's token-based clone URL
        clone_url = f"https://x-access-token:{access_token}@github.com/{owner}/{repo}.git"

        # Ensure target directory exists
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        # Shallow clone specific branch
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            "--single-branch",
            clone_url,
            target_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"Git clone failed: {result.stderr}")

        # Get the commit SHA of the cloned HEAD
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target_path,
            capture_output=True,
            text=True,
        )
        commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""

        return CloneResult(
            local_path=target_path,
            commit_sha=commit_sha,
            branch_name=branch,
            metadata={"clone_url": clone_url, "shallow": True},
        )

    async def validate_repository_access(
        self,
        access_token: str,
        owner: str,
        repo: str,
    ) -> bool:
        """Validate that the token has access to the repository."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}",
                headers=self._get_headers(access_token),
                timeout=30.0,
            )
            return response.status_code == 200

    async def revoke_token(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
    ) -> bool:
        """Revoke an OAuth token."""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self._base_url}/applications/{client_id}/token",
                auth=(client_id, client_secret),
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": self._api_version,
                },
                json={"access_token": access_token},
                timeout=30.0,
            )
            return response.status_code == 204

    def _normalize_repository(self, data: dict[str, Any]) -> ProviderRepository:
        """Normalize GitHub repository data to ProviderRepository."""
        owner_data = data.get("owner", {})
        return ProviderRepository(
            provider_repo_id=str(data["id"]),
            name=data["name"],
            full_name=data["full_name"],
            owner=owner_data.get("login", ""),
            is_private=data.get("private", False),
            default_branch=data.get("default_branch", "main"),
            description=data.get("description"),
            primary_language=data.get("language"),
            html_url=data.get("html_url"),
            clone_url=data.get("clone_url"),
            ssh_url=data.get("ssh_url"),
            updated_at=self._parse_datetime(data.get("updated_at")),
            pushed_at=self._parse_datetime(data.get("pushed_at")),
            size_kb=data.get("size"),
            topics=data.get("topics", []),
            metadata={k: v for k, v in data.items() if k not in {
                "id", "name", "full_name", "owner", "private", "default_branch",
                "description", "language", "html_url", "clone_url", "ssh_url",
                "updated_at", "pushed_at", "size", "topics"
            }},
        )

    def _normalize_branch(self, data: dict[str, Any]) -> ProviderBranch:
        """Normalize GitHub branch data to ProviderBranch."""
        commit_data = data.get("commit", {})
        return ProviderBranch(
            name=data["name"],
            commit_sha=commit_data.get("sha", ""),
            is_default=data.get("name") == data.get("default_branch", False),
            is_protected=data.get("protected", False),
            metadata=data,
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None


def register_github_provider(
    client_id: str | None = None,
    client_secret: str | None = None,
    base_url: str = "https://api.github.com",
    web_base_url: str = "https://github.com",
) -> GitHubProvider:
    """Register the GitHub provider in the global registry."""
    provider = GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        web_base_url=web_base_url,
    )
    get_provider_registry().register(provider)
    return provider