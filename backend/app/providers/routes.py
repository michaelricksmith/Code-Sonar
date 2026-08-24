"""Provider connection API routes for OAuth flows."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.providers.base import ProviderRegistry, get_provider_registry
from app.providers.github import GitHubProvider, register_github_provider
from app.workspace.models import ProviderType
from app.workspace.store import (
    create_provider_connection,
    delete_provider_connection,
    get_provider_connection,
    get_provider_connection_by_provider,
    get_provider_connections_for_workspace,
    get_workspace,
    update_provider_connection,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])


# Initialize providers (in production, this would be in startup event)
def _init_providers() -> ProviderRegistry:
    registry = get_provider_registry()
    if not registry.get_available_types():
        # Register GitHub provider with env config
        register_github_provider()
    return registry


@router.get("/available", response_model=list[dict[str, str]])
async def list_available_providers() -> list[dict[str, str]]:
    """List available repository provider types."""
    registry = _init_providers()
    return [
        {"type": p.provider_type, "display_name": p.display_name, "scopes": p.required_scopes}
        for p in registry.list_providers()
    ]


@router.get("/{workspace_id}/connect/{provider_type}")
async def initiate_provider_connection(
    workspace_id: str,
    provider_type: ProviderType,
    current_user: User = Depends(get_current_user),
    redirect_uri: str = Query(..., description="Frontend callback URL"),
) -> RedirectResponse:
    """Initiate OAuth flow for a provider connection."""
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

    registry = _init_providers()
    provider = registry.get(provider_type.value)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider {provider_type.value} not implemented",
        )

    # Generate state token for CSRF protection
    import secrets
    state = secrets.token_urlsafe(32)

    # Store state in workspace metadata for verification in callback
    workspace.metadata = getattr(workspace, 'metadata', {}) or {}
    workspace.metadata[f"oauth_state_{provider_type.value}"] = state
    update_workspace(workspace)

    auth_url = provider.get_authorization_url(
        client_id=provider._client_id,
        redirect_uri=redirect_uri,
        state=state,
        scopes=provider.required_scopes,
    )

    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/{workspace_id}/callback/{provider_type}")
async def provider_oauth_callback(
    workspace_id: str,
    provider_type: ProviderType,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    """Handle OAuth callback from provider."""
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Get frontend URL for redirect (from environment or default)
    import os
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    callback_path = f"/onboarding/provider-callback?provider={provider_type.value}"

    if error:
        # Redirect to frontend with error
        error_msg = error_description or error
        return RedirectResponse(
            url=f"{frontend_url}{callback_path}&error={error_msg}",
            status_code=status.HTTP_302_FOUND,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{frontend_url}{callback_path}&error=missing_code_or_state",
            status_code=status.HTTP_302_FOUND,
        )

    # Verify state token
    stored_state = (workspace.metadata or {}).get(f"oauth_state_{provider_type.value}")
    if not stored_state or stored_state != state:
        return RedirectResponse(
            url=f"{frontend_url}{callback_path}&error=invalid_state",
            status_code=status.HTTP_302_FOUND,
        )

    registry = _init_providers()
    provider = registry.get(provider_type.value)
    if not provider:
        return RedirectResponse(
            url=f"{frontend_url}{callback_path}&error=provider_not_implemented",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        # Exchange code for tokens
        token_data = await provider.exchange_code_for_tokens(
            client_id=provider._client_id,
            client_secret=provider._client_secret,
            redirect_uri=request.query_params.get("redirect_uri", f"{frontend_url}/auth/callback"),
            code=code,
        )

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        scope = token_data.get("scope", "")

        # Get authenticated user from provider
        provider_user = await provider.get_authenticated_user(access_token)

        # Check if connection already exists
        existing = get_provider_connection_by_provider(workspace_id, provider_type)
        if existing:
            # Update existing connection
            existing.access_token_encrypted = access_token  # TODO: encrypt
            existing.refresh_token_encrypted = refresh_token  # TODO: encrypt
            existing.token_expires_at = None  # GitHub OAuth tokens don't expire
            existing.scopes = scope.split() if scope else provider.required_scopes
            existing.provider_user_id = provider_user.provider_user_id
            existing.provider_username = provider_user.username
            existing.provider_avatar_url = provider_user.avatar_url
            existing.metadata = provider_user.metadata or {}
            existing.is_active = True
            update_provider_connection(existing)
            conn = existing
        else:
            # Create new connection
            from datetime import datetime, timedelta
            token_expires_at = None
            if expires_in:
                token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            conn = create_provider_connection(
                workspace_id=workspace_id,
                provider_type=provider_type,
                provider_user_id=provider_user.provider_user_id,
                provider_username=provider_user.username,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
                scopes=scope.split() if scope else provider.required_scopes,
                provider_avatar_url=provider_user.avatar_url,
                metadata=provider_user.metadata or {},
            )

        # Sync repositories
        await sync_repositories_from_provider(workspace_id, provider, conn, access_token)

        # Update workspace onboarding step
        workspace.onboarding_step = "repository_select"
        workspace.active_repository_id = None
        update_workspace(workspace)

        # Clear state
        if workspace.metadata:
            workspace.metadata.pop(f"oauth_state_{provider_type.value}", None)
            update_workspace(workspace)

        return RedirectResponse(
            url=f"{frontend_url}{callback_path}&success=true&connection_id={conn.id}",
            status_code=status.HTTP_302_FOUND,
        )

    except Exception as e:
        return RedirectResponse(
            url=f"{frontend_url}{callback_path}&error={str(e)}",
            status_code=status.HTTP_302_FOUND,
        )


async def sync_repositories_from_provider(
    workspace_id: str,
    provider: GitHubProvider,
    connection,
    access_token: str,
) -> None:
    """Sync repositories from the provider."""
    try:
        provider_repos = await provider.list_repositories(access_token)
        # Convert to dict format for store.sync_repositories_from_provider
        repos_data = []
        for r in provider_repos:
            repos_data.append({
                "id": r.provider_repo_id,
                "name": r.name,
                "full_name": r.full_name,
                "owner": {"login": r.owner},
                "private": r.is_private,
                "default_branch": r.default_branch,
                "description": r.description,
                "language": r.primary_language,
                "html_url": r.html_url,
                "clone_url": r.clone_url,
                "ssh_url": r.ssh_url,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
                "size": r.size_kb,
                "topics": r.topics,
                "metadata": r.metadata,
            })

        from app.workspace.store import sync_repositories_from_provider as store_sync
        store_sync(workspace_id, provider_type, repos_data)

    except Exception:
        # Log but don't fail the callback
        pass


@router.get("/{workspace_id}/connections", response_model=list[dict])
async def list_connections(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
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
    return [conn.to_dict() for conn in conns]


@router.get("/{workspace_id}/connections/{connection_id}", response_model=dict)
async def get_connection(
    workspace_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
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

    conn = get_provider_connection(connection_id)
    if not conn or conn.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider connection not found",
        )

    return conn.to_dict(include_tokens=False)


@router.delete("/{workspace_id}/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_provider(
    workspace_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Disconnect a provider (revoke tokens and delete connection)."""
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

    # Revoke token with provider (best effort)
    registry = _init_providers()
    provider = registry.get(conn.provider_type.value)
    if provider and conn.access_token_encrypted:
        try:
            await provider.revoke_token(
                client_id=provider._client_id,
                client_secret=provider._client_secret,
                access_token=conn.access_token_encrypted,
            )
        except Exception:
            pass  # Best effort

    delete_provider_connection(connection_id)

    # If this was the active connection, clear workspace active repo
    if workspace.active_repository_id:
        workspace.active_repository_id = None
        workspace.active_branch = None
        update_workspace(workspace)


@router.post("/{workspace_id}/connections/{connection_id}/sync", response_model=dict)
async def sync_connection(
    workspace_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually trigger a repository sync for a connection."""
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

    if not conn.access_token_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No access token available for sync",
        )

    registry = _init_providers()
    provider = registry.get(conn.provider_type.value)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not implemented",
        )

    try:
        await sync_repositories_from_provider(workspace_id, provider, conn, conn.access_token_encrypted)
        return {"message": "Sync completed", "synced": True}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        )