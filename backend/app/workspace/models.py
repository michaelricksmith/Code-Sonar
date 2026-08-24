"""Workspace models for onboarding and repository management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class OnboardingStep(str, Enum):
    """Onboarding flow steps."""

    WELCOME = "welcome"
    WORKSPACE_CREATE = "workspace_create"
    PROVIDER_SELECT = "provider_select"
    PROVIDER_CONNECT = "provider_connect"
    REPOSITORY_SELECT = "repository_select"
    BRANCH_SELECT = "branch_select"
    SCAN_CONFIGURE = "scan_configure"
    SCAN_RUNNING = "scan_running"
    SCORE_REVEAL = "score_reveal"
    COMPLETE = "complete"


class ProviderType(str, Enum):
    """Supported repository providers."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    AZURE_DEVOPS = "azure_devops"
    LOCAL = "local"


@dataclass
class Workspace:
    """User workspace containing repositories and provider connections."""

    id: str
    name: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    onboarding_step: OnboardingStep = OnboardingStep.WELCOME
    onboarding_completed_at: datetime | None = None
    active_repository_id: str | None = None
    active_branch: str | None = None
    last_scan_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, owner_id: str) -> "Workspace":
        now = datetime.now()
        return cls(
            id=str(uuid4()),
            name=name.strip(),
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "onboarding_step": self.onboarding_step.value,
            "onboarding_completed_at": self.onboarding_completed_at.isoformat() if self.onboarding_completed_at else None,
            "active_repository_id": self.active_repository_id,
            "active_branch": self.active_branch,
            "last_scan_id": self.last_scan_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workspace":
        return cls(
            id=data["id"],
            name=data["name"],
            owner_id=data["owner_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            onboarding_step=OnboardingStep(data.get("onboarding_step", "welcome")),
            onboarding_completed_at=datetime.fromisoformat(data["onboarding_completed_at"]) if data.get("onboarding_completed_at") else None,
            active_repository_id=data.get("active_repository_id"),
            active_branch=data.get("active_branch"),
            last_scan_id=data.get("last_scan_id"),
        )


@dataclass
class ProviderConnection:
    """A user's connection to a repository provider (e.g., GitHub)."""

    id: str
    workspace_id: str
    provider_type: ProviderType
    provider_user_id: str  # Provider's user ID (e.g., GitHub user ID)
    provider_username: str  # Provider's username/login
    provider_avatar_url: str | None = None
    access_token_encrypted: str | None = None  # Encrypted OAuth access token
    refresh_token_encrypted: str | None = None  # Encrypted refresh token
    token_expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    is_active: bool = True
    connected_at: datetime = field(default_factory=datetime.now)
    last_synced_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)  # Provider-specific data

    @classmethod
    def create(
        cls,
        workspace_id: str,
        provider_type: ProviderType,
        provider_user_id: str,
        provider_username: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: datetime | None = None,
        scopes: list[str] | None = None,
        provider_avatar_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ProviderConnection":
        return cls(
            id=str(uuid4()),
            workspace_id=workspace_id,
            provider_type=provider_type,
            provider_user_id=provider_user_id,
            provider_username=provider_username,
            provider_avatar_url=provider_avatar_url,
            access_token_encrypted=access_token,  # TODO: encrypt in production
            refresh_token_encrypted=refresh_token,  # TODO: encrypt in production
            token_expires_at=token_expires_at,
            scopes=scopes or [],
            metadata=metadata or {},
        )

    def to_dict(self, include_tokens: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "provider_type": self.provider_type.value,
            "provider_user_id": self.provider_user_id,
            "provider_username": self.provider_username,
            "provider_avatar_url": self.provider_avatar_url,
            "token_expires_at": self.token_expires_at.isoformat() if self.token_expires_at else None,
            "scopes": self.scopes,
            "is_active": self.is_active,
            "connected_at": self.connected_at.isoformat(),
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "metadata": self.metadata,
        }
        if include_tokens:
            d["access_token"] = self.access_token_encrypted
            d["refresh_token"] = self.refresh_token_encrypted
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderConnection":
        return cls(
            id=data["id"],
            workspace_id=data["workspace_id"],
            provider_type=ProviderType(data["provider_type"]),
            provider_user_id=data["provider_user_id"],
            provider_username=data["provider_username"],
            provider_avatar_url=data.get("provider_avatar_url"),
            access_token_encrypted=data.get("access_token"),
            refresh_token_encrypted=data.get("refresh_token"),
            token_expires_at=datetime.fromisoformat(data["token_expires_at"]) if data.get("token_expires_at") else None,
            scopes=data.get("scopes", []),
            is_active=data.get("is_active", True),
            connected_at=datetime.fromisoformat(data["connected_at"]),
            last_synced_at=datetime.fromisoformat(data["last_synced_at"]) if data.get("last_synced_at") else None,
            metadata=data.get("metadata", {}),
        )


@dataclass
class Repository:
    """A repository accessible through a provider connection."""

    id: str
    workspace_id: str
    provider_connection_id: str
    provider_repo_id: str  # Provider's repository ID (e.g., GitHub repo ID)
    name: str  # Repository name (e.g., "code-sonar")
    full_name: str  # Full name with owner (e.g., "owner/code-sonar")
    owner: str  # Repository owner
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
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    synced_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(
        cls,
        workspace_id: str,
        provider_connection_id: str,
        provider_repo_id: str,
        name: str,
        full_name: str,
        owner: str,
        is_private: bool,
        default_branch: str,
        description: str | None = None,
        primary_language: str | None = None,
        html_url: str | None = None,
        clone_url: str | None = None,
        ssh_url: str | None = None,
        updated_at: datetime | None = None,
        pushed_at: datetime | None = None,
        size_kb: int | None = None,
        topics: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Repository":
        return cls(
            id=str(uuid4()),
            workspace_id=workspace_id,
            provider_connection_id=provider_connection_id,
            provider_repo_id=provider_repo_id,
            name=name,
            full_name=full_name,
            owner=owner,
            is_private=is_private,
            default_branch=default_branch,
            description=description,
            primary_language=primary_language,
            html_url=html_url,
            clone_url=clone_url,
            ssh_url=ssh_url,
            updated_at=updated_at,
            pushed_at=pushed_at,
            size_kb=size_kb,
            topics=topics or [],
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "provider_connection_id": self.provider_connection_id,
            "provider_repo_id": self.provider_repo_id,
            "name": self.name,
            "full_name": self.full_name,
            "owner": self.owner,
            "is_private": self.is_private,
            "default_branch": self.default_branch,
            "description": self.description,
            "primary_language": self.primary_language,
            "html_url": self.html_url,
            "clone_url": self.clone_url,
            "ssh_url": self.ssh_url,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "pushed_at": self.pushed_at.isoformat() if self.pushed_at else None,
            "size_kb": self.size_kb,
            "topics": self.topics,
            "metadata": self.metadata,
            "synced_at": self.synced_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Repository":
        return cls(
            id=data["id"],
            workspace_id=data["workspace_id"],
            provider_connection_id=data["provider_connection_id"],
            provider_repo_id=data["provider_repo_id"],
            name=data["name"],
            full_name=data["full_name"],
            owner=data["owner"],
            is_private=data["is_private"],
            default_branch=data["default_branch"],
            description=data.get("description"),
            primary_language=data.get("primary_language"),
            html_url=data.get("html_url"),
            clone_url=data.get("clone_url"),
            ssh_url=data.get("ssh_url"),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            pushed_at=datetime.fromisoformat(data["pushed_at"]) if data.get("pushed_at") else None,
            size_kb=data.get("size_kb"),
            topics=data.get("topics", []),
            metadata=data.get("metadata", {}),
            synced_at=datetime.fromisoformat(data["synced_at"]) if data.get("synced_at") else datetime.now(),
        )


@dataclass
class Branch:
    """A repository branch."""

    id: str
    repository_id: str
    name: str
    commit_sha: str
    is_default: bool
    is_protected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    synced_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(
        cls,
        repository_id: str,
        name: str,
        commit_sha: str,
        is_default: bool,
        is_protected: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> "Branch":
        return cls(
            id=str(uuid4()),
            repository_id=repository_id,
            name=name,
            commit_sha=commit_sha,
            is_default=is_default,
            is_protected=is_protected,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repository_id": self.repository_id,
            "name": self.name,
            "commit_sha": self.commit_sha,
            "is_default": self.is_default,
            "is_protected": self.is_protected,
            "metadata": self.metadata,
            "synced_at": self.synced_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Branch":
        return cls(
            id=data["id"],
            repository_id=data["repository_id"],
            name=data["name"],
            commit_sha=data["commit_sha"],
            is_default=data["is_default"],
            is_protected=data.get("is_protected", False),
            metadata=data.get("metadata", {}),
            synced_at=datetime.fromisoformat(data["synced_at"]) if data.get("synced_at") else datetime.now(),
        )