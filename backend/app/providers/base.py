"""Repository provider abstraction for remote source control platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class ProviderRepository:
    """Normalized repository representation across providers."""

    provider_repo_id: str
    name: str
    full_name: str
    owner: str
    is_private: bool
    default_branch: str
    description: str | None = None
    primary_language: str | None = None
    html_url: str | None = None
    clone_url: str | None = None
    ssh_url: str | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None
    size_kb: int | None = None
    topics: list[str] | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ProviderBranch:
    """Normalized branch representation across providers."""

    name: str
    commit_sha: str
    is_default: bool
    is_protected: bool = False
    metadata: dict[str, Any] | None = None


@dataclass
class ProviderUser:
    """Normalized user representation across providers."""

    provider_user_id: str
    username: str
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class CloneResult:
    """Result of cloning a repository."""

    local_path: str
    commit_sha: str
    branch_name: str
    metadata: dict[str, Any] | None = None


class RepositoryProvider(ABC):
    """Abstract base class for repository providers.

    Implementations must handle provider-specific authentication,
    API calls, and data normalization.
    """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Unique provider identifier (e.g., 'github', 'gitlab')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable provider name."""
        pass

    @property
    @abstractmethod
    def required_scopes(self) -> list[str]:
        """Minimum OAuth scopes required for this provider."""
        pass

    @abstractmethod
    def get_authorization_url(
        self,
        client_id: str,
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Generate the OAuth authorization URL for this provider."""
        pass

    @abstractmethod
    async def exchange_code_for_tokens(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code: str,
    ) -> dict[str, Any]:
        """Exchange OAuth authorization code for access/refresh tokens.

        Returns a dict with at least:
        - access_token: str
        - refresh_token: str (optional)
        - expires_in: int (seconds, optional)
        - scope: str (space-separated, optional)
        """
        pass

    @abstractmethod
    async def refresh_access_token(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> dict[str, Any]:
        """Refresh an expired access token.

        Returns a dict with at least:
        - access_token: str
        - refresh_token: str (optional, may be same)
        - expires_in: int (seconds, optional)
        """
        pass

    @abstractmethod
    async def get_authenticated_user(
        self,
        access_token: str,
    ) -> ProviderUser:
        """Get the authenticated user's information."""
        pass

    @abstractmethod
    async def list_repositories(
        self,
        access_token: str,
        page: int = 1,
        per_page: int = 100,
        visibility: str | None = None,  # "all", "public", "private"
        affiliation: str | None = None,  # "owner", "collaborator", "organization_member"
    ) -> list[ProviderRepository]:
        """List repositories accessible to the authenticated user."""
        pass

    @abstractmethod
    async def get_repository(
        self,
        access_token: str,
        owner: str,
        repo: str,
    ) -> ProviderRepository | None:
        """Get a specific repository by owner and name."""
        pass

    @abstractmethod
    async def list_branches(
        self,
        access_token: str,
        owner: str,
        repo: str,
        page: int = 1,
        per_page: int = 100,
    ) -> list[ProviderBranch]:
        """List branches for a repository."""
        pass

    @abstractmethod
    async def get_branch(
        self,
        access_token: str,
        owner: str,
        repo: str,
        branch: str,
    ) -> ProviderBranch | None:
        """Get a specific branch."""
        pass

    @abstractmethod
    async def clone_repository(
        self,
        access_token: str,
        owner: str,
        repo: str,
        branch: str,
        target_path: str,
    ) -> CloneResult:
        """Clone a repository to a local path for scanning.

        The implementation should:
        - Use the access token for authentication
        - Clone only the specified branch (shallow clone preferred)
        - Return the local path and commit SHA
        """
        pass

    @abstractmethod
    async def validate_repository_access(
        self,
        access_token: str,
        owner: str,
        repo: str,
    ) -> bool:
        """Validate that the token has access to the repository."""
        pass

    @abstractmethod
    async def revoke_token(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
    ) -> bool:
        """Revoke an access token (optional, for disconnect)."""
        pass


class ProviderRegistry:
    """Registry for repository providers."""

    def __init__(self) -> None:
        self._providers: dict[str, RepositoryProvider] = {}

    def register(self, provider: RepositoryProvider) -> None:
        """Register a provider implementation."""
        self._providers[provider.provider_type] = provider

    def get(self, provider_type: str) -> RepositoryProvider | None:
        """Get a provider by type."""
        return self._providers.get(provider_type)

    def list_providers(self) -> list[RepositoryProvider]:
        """List all registered providers."""
        return list(self._providers.values())

    def get_available_types(self) -> list[str]:
        """Get list of available provider types."""
        return list(self._providers.keys())


# Global registry instance
_provider_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Get the global provider registry."""
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = ProviderRegistry()
    return _provider_registry


def set_provider_registry(registry: ProviderRegistry) -> None:
    """Replace the global provider registry (for testing)."""
    global _provider_registry
    _provider_registry = registry