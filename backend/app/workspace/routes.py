"""Workspace API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.workspace.models import (
    Branch,
    OnboardingStep,
    ProviderConnection,
    ProviderType,
    Repository,
    Workspace,
)
from app.workspace.store import (
    create_provider_connection,
    create_repository,
    create_workspace,
    delete_provider_connection,
    delete_repository,
    delete_workspace,
    get_branch,
    get_branches_for_repository,
    get_default_branch,
    get_provider_connection,
    get_provider_connection_by_provider,
    get_provider_connections_for_workspace,
    get_repositories_for_connection,
    get_repositories_for_workspace,
    get_workspace,
    get_workspaces_for_owner,
    sync_branches_from_provider,
    sync_repositories_from_provider,
    update_provider_connection,
    update_repository,
    update_workspace,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    """Request to create a workspace."""
    name: str


class WorkspaceResponse(BaseModel):
    """Workspace response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    onboarding_step: OnboardingStep
    onboarding_completed_at: datetime | None = None
    active_repository_id: str | None = None
    active_branch: str | None = None
    last_scan_id: str | None = None

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> "WorkspaceResponse":
        return cls(
            id=workspace.id,
            name=workspace.name,
            owner_id=workspace.owner_id,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
            onboarding_step=workspace.onboarding_step,
            onboarding_completed_at=workspace.onboarding_completed_at,
            active_repository_id=workspace.active_repository_id,
            active_branch=workspace.active_branch,
            last_scan_id=workspace.last_scan_id,
        )


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_endpoint(
    request: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
) -> WorkspaceResponse:
    """Create a new workspace for the current user."""
    name = request.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace name is required",
        )

    workspace = create_workspace(name, current_user.id)
    return WorkspaceResponse.from_workspace(workspace)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
) -> list[WorkspaceResponse]:
    """List all workspaces for the current user."""
    workspaces = get_workspaces_for_owner(current_user.id)
    return [WorkspaceResponse.from_workspace(w) for w in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace_endpoint(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
) -> WorkspaceResponse:
    """Get a specific workspace."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return WorkspaceResponse.from_workspace(workspace)


class WorkspaceUpdateRequest(BaseModel):
    """Request to update a workspace."""
    name: str | None = None
    onboarding_step: OnboardingStep | None = None
    active_repository_id: str | None = None
    active_branch: str | None = None
    last_scan_id: str | None = None
    onboarding_completed_at: datetime | None = None


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace_endpoint(
    workspace_id: str,
    request: WorkspaceUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> WorkspaceResponse:
    """Update a workspace (e.g., onboarding step)."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if request.name is not None:
        workspace.name = request.name.strip()
    if request.onboarding_step is not None:
        workspace.onboarding_step = request.onboarding_step
    if request.active_repository_id is not None:
        workspace.active_repository_id = request.active_repository_id
    if request.active_branch is not None:
        workspace.active_branch = request.active_branch
    if request.last_scan_id is not None:
        workspace.last_scan_id = request.last_scan_id
    if request.onboarding_completed_at is not None:
        workspace.onboarding_completed_at = request.onboarding_completed_at

    update_workspace(workspace)
    return WorkspaceResponse.from_workspace(workspace)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_endpoint(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a workspace."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    delete_workspace(workspace_id)


# Provider connection endpoints
class ProviderConnectionResponse(BaseModel):
    """Provider connection response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    provider_type: ProviderType
    provider_user_id: str
    provider_username: str
    provider_avatar_url: str | None = None
    token_expires_at: datetime | None = None
    scopes: list[str] = []
    is_active: bool = True
    connected_at: datetime
    last_synced_at: datetime | None = None
    metadata: dict[str, Any] = {}

    @classmethod
    def from_connection(cls, conn: ProviderConnection, include_tokens: bool = False) -> "ProviderConnectionResponse":
        data = conn.to_dict(include_tokens=include_tokens)
        return cls(**data)


@router.get("/{workspace_id}/providers", response_model=list[ProviderConnectionResponse])
async def list_provider_connections(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
) -> list[ProviderConnectionResponse]:
    """List all provider connections for a workspace."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    conns = get_provider_connections_for_workspace(workspace_id)
    return [ProviderConnectionResponse.from_connection(c) for c in conns]


@router.get("/{workspace_id}/providers/{provider_type}", response_model=ProviderConnectionResponse)
async def get_provider_connection_endpoint(
    workspace_id: str,
    provider_type: ProviderType,
    current_user: User = Depends(get_current_user),
) -> ProviderConnectionResponse:
    """Get a specific provider connection."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    conn = get_provider_connection_by_provider(workspace_id, provider_type)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider_type.value} connection found",
        )
    return ProviderConnectionResponse.from_connection(conn)


@router.delete("/{workspace_id}/providers/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_connection_endpoint(
    workspace_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Disconnect a provider (revoke connection)."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    conn = get_provider_connection(connection_id)
    if not conn or conn.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider connection not found",
        )

    delete_provider_connection(connection_id)


# Repository endpoints
class RepositoryResponse(BaseModel):
    """Repository response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    provider_connection_id: str
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
    topics: list[str] = []
    metadata: dict[str, Any] = {}
    synced_at: datetime

    @classmethod
    def from_repository(cls, repo: Repository) -> "RepositoryResponse":
        return cls(**repo.to_dict())


@router.get("/{workspace_id}/repositories", response_model=list[RepositoryResponse])
async def list_repositories(
    workspace_id: str,
    provider_type: ProviderType | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> list[RepositoryResponse]:
    """List all repositories for a workspace, optionally filtered by provider."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    repos = get_repositories_for_workspace(workspace_id)
    if provider_type:
        # Filter by provider type via connection
        conns = get_provider_connections_for_workspace(workspace_id)
        provider_conn_ids = {c.id for c in conns if c.provider_type == provider_type}
        repos = [r for r in repos if r.provider_connection_id in provider_conn_ids]

    return [RepositoryResponse.from_repository(r) for r in repos]


@router.get("/{workspace_id}/repositories/{repo_id}", response_model=RepositoryResponse)
async def get_repository_endpoint(
    workspace_id: str,
    repo_id: str,
    current_user: User = Depends(get_current_user),
) -> RepositoryResponse:
    """Get a specific repository."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    repos = get_repositories_for_workspace(workspace_id)
    repo = next((r for r in repos if r.id == repo_id), None)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return RepositoryResponse.from_repository(repo)


@router.post("/{workspace_id}/repositories/sync", response_model=list[RepositoryResponse])
async def sync_repositories(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
) -> list[RepositoryResponse]:
    """Trigger a repository sync from all connected providers."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # This would call the provider abstraction to fetch and sync repos
    # For now, return current state
    repos = get_repositories_for_workspace(workspace_id)
    return [RepositoryResponse.from_repository(r) for r in repos]


# Branch endpoints
class BranchResponse(BaseModel):
    """Branch response model."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    name: str
    commit_sha: str
    is_default: bool
    is_protected: bool = False
    metadata: dict[str, Any] = {}
    synced_at: datetime

    @classmethod
    def from_branch(cls, branch: Branch) -> "BranchResponse":
        return cls(**branch.to_dict())


@router.get("/{workspace_id}/repositories/{repo_id}/branches", response_model=list[BranchResponse])
async def list_branches(
    workspace_id: str,
    repo_id: str,
    current_user: User = Depends(get_current_user),
) -> list[BranchResponse]:
    """List all branches for a repository."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    repos = get_repositories_for_workspace(workspace_id)
    repo = next((r for r in repos if r.id == repo_id), None)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    branches = get_branches_for_repository(repo_id)
    return [BranchResponse.from_branch(b) for b in branches]


@router.get("/{workspace_id}/repositories/{repo_id}/branches/default", response_model=BranchResponse)
async def get_default_branch_endpoint(
    workspace_id: str,
    repo_id: str,
    current_user: User = Depends(get_current_user),
) -> BranchResponse:
    """Get the default branch for a repository."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    branch = get_default_branch(repo_id)
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No default branch found",
        )
    return BranchResponse.from_branch(branch)


@router.post("/{workspace_id}/repositories/{repo_id}/branches/sync", response_model=list[BranchResponse])
async def sync_branches(
    workspace_id: str,
    repo_id: str,
    current_user: User = Depends(get_current_user),
) -> list[BranchResponse]:
    """Trigger a branch sync from the provider."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    repos = get_repositories_for_workspace(workspace_id)
    repo = next((r for r in repos if r.id == repo_id), None)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    # This would call the provider abstraction to fetch and sync branches
    # For now, return current state
    branches = get_branches_for_repository(repo_id)
    return [BranchResponse.from_branch(b) for b in branches]