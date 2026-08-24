"""Workspace storage (in-memory for MVP, replaceable with database)."""

from __future__ import annotations

from typing import Any

from app.workspace.models import (
    Branch,
    OnboardingStep,
    ProviderConnection,
    ProviderType,
    Repository,
    Workspace,
)

# In-memory stores
_workspaces: dict[str, Workspace] = {}  # workspace_id -> Workspace
_workspace_by_owner: dict[str, set[str]] = {}  # owner_id -> set of workspace_ids
_provider_connections: dict[str, ProviderConnection] = {}  # connection_id -> ProviderConnection
_provider_connections_by_workspace: dict[str, set[str]] = {}  # workspace_id -> set of connection_ids
_repositories: dict[str, Repository] = {}  # repo_id -> Repository
_repositories_by_connection: dict[str, set[str]] = {}  # connection_id -> set of repo_ids
_branches: dict[str, Branch] = {}  # branch_id -> Branch
_branches_by_repo: dict[str, set[str]] = {}  # repo_id -> set of branch_ids


def _index_workspace(workspace: Workspace) -> None:
    _workspaces[workspace.id] = workspace
    _workspace_by_owner.setdefault(workspace.owner_id, set()).add(workspace.id)


def _unindex_workspace(workspace_id: str) -> None:
    workspace = _workspaces.pop(workspace_id, None)
    if workspace:
        _workspace_by_owner.get(workspace.owner_id, set()).discard(workspace_id)


def _index_connection(conn: ProviderConnection) -> None:
    _provider_connections[conn.id] = conn
    _provider_connections_by_workspace.setdefault(conn.workspace_id, set()).add(conn.id)


def _unindex_connection(conn_id: str) -> None:
    conn = _provider_connections.pop(conn_id, None)
    if conn:
        _provider_connections_by_workspace.get(conn.workspace_id, set()).discard(conn_id)


def _index_repository(repo: Repository) -> None:
    _repositories[repo.id] = repo
    _repositories_by_connection.setdefault(repo.provider_connection_id, set()).add(repo.id)


def _unindex_repository(repo_id: str) -> None:
    repo = _repositories.pop(repo_id, None)
    if repo:
        _repositories_by_connection.get(repo.provider_connection_id, set()).discard(repo_id)


def _index_branch(branch: Branch) -> None:
    _branches[branch.id] = branch
    _branches_by_repo.setdefault(branch.repository_id, set()).add(branch.id)


def _unindex_branch(branch_id: str) -> None:
    branch = _branches.pop(branch_id, None)
    if branch:
        _branches_by_repo.get(branch.repository_id, set()).discard(branch_id)


# Workspace operations
def create_workspace(name: str, owner_id: str) -> Workspace:
    workspace = Workspace.create(name, owner_id)
    _index_workspace(workspace)
    return workspace


def get_workspace(workspace_id: str) -> Workspace | None:
    return _workspaces.get(workspace_id)


def get_workspaces_for_owner(owner_id: str) -> list[Workspace]:
    ids = _workspace_by_owner.get(owner_id, set())
    return [_workspaces[i] for i in ids if i in _workspaces]


def update_workspace(workspace: Workspace) -> Workspace:
    workspace.updated_at = workspace.updated_at.__class__.now()
    _workspaces[workspace.id] = workspace
    return workspace


def delete_workspace(workspace_id: str) -> bool:
    workspace = _workspaces.get(workspace_id)
    if not workspace:
        return False
    # Cascade delete connections, repos, branches
    for conn_id in list(_provider_connections_by_workspace.get(workspace_id, set())):
        delete_provider_connection(conn_id)
    _unindex_workspace(workspace_id)
    return True


# Provider connection operations
def create_provider_connection(
    workspace_id: str,
    provider_type: ProviderType,
    provider_user_id: str,
    provider_username: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
    token_expires_at: Any = None,
    scopes: list[str] | None = None,
    provider_avatar_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProviderConnection:
    conn = ProviderConnection.create(
        workspace_id=workspace_id,
        provider_type=provider_type,
        provider_user_id=provider_user_id,
        provider_username=provider_username,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
        scopes=scopes,
        provider_avatar_url=provider_avatar_url,
        metadata=metadata,
    )
    _index_connection(conn)
    return conn


def get_provider_connection(conn_id: str) -> ProviderConnection | None:
    return _provider_connections.get(conn_id)


def get_provider_connections_for_workspace(workspace_id: str) -> list[ProviderConnection]:
    ids = _provider_connections_by_workspace.get(workspace_id, set())
    return [_provider_connections[i] for i in ids if i in _provider_connections]


def get_provider_connection_by_provider(
    workspace_id: str, provider_type: ProviderType
) -> ProviderConnection | None:
    for conn in get_provider_connections_for_workspace(workspace_id):
        if conn.provider_type == provider_type and conn.is_active:
            return conn
    return None


def update_provider_connection(conn: ProviderConnection) -> ProviderConnection:
    conn.last_synced_at = conn.last_synced_at.__class__.now()
    _provider_connections[conn.id] = conn
    return conn


def delete_provider_connection(conn_id: str) -> bool:
    conn = _provider_connections.get(conn_id)
    if not conn:
        return False
    # Cascade delete repos and branches
    for repo_id in list(_repositories_by_connection.get(conn_id, set())):
        delete_repository(repo_id)
    _unindex_connection(conn_id)
    return True


# Repository operations
def create_repository(
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
    updated_at: Any = None,
    pushed_at: Any = None,
    size_kb: int | None = None,
    topics: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Repository:
    repo = Repository.create(
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
        topics=topics,
        metadata=metadata,
    )
    _index_repository(repo)
    return repo


def get_repository(repo_id: str) -> Repository | None:
    return _repositories.get(repo_id)


def get_repositories_for_connection(conn_id: str) -> list[Repository]:
    ids = _repositories_by_connection.get(conn_id, set())
    return [_repositories[i] for i in ids if i in _repositories]


def get_repositories_for_workspace(workspace_id: str) -> list[Repository]:
    conns = get_provider_connections_for_workspace(workspace_id)
    repos: list[Repository] = []
    for conn in conns:
        repos.extend(get_repositories_for_connection(conn.id))
    return repos


def update_repository(repo: Repository) -> Repository:
    repo.synced_at = repo.synced_at.__class__.now()
    _repositories[repo.id] = repo
    return repo


def delete_repository(repo_id: str) -> bool:
    repo = _repositories.get(repo_id)
    if not repo:
        return False
    # Cascade delete branches
    for branch_id in list(_branches_by_repo.get(repo_id, set())):
        delete_branch(branch_id)
    _unindex_repository(repo_id)
    return True


# Branch operations
def create_branch(
    repository_id: str,
    name: str,
    commit_sha: str,
    is_default: bool,
    is_protected: bool = False,
    metadata: dict[str, Any] | None = None,
) -> Branch:
    branch = Branch.create(
        repository_id=repository_id,
        name=name,
        commit_sha=commit_sha,
        is_default=is_default,
        is_protected=is_protected,
        metadata=metadata,
    )
    _index_branch(branch)
    return branch


def get_branch(branch_id: str) -> Branch | None:
    return _branches.get(branch_id)


def get_branches_for_repository(repo_id: str) -> list[Branch]:
    ids = _branches_by_repo.get(repo_id, set())
    return [_branches[i] for i in ids if i in _branches]


def get_default_branch(repo_id: str) -> Branch | None:
    for branch in get_branches_for_repository(repo_id):
        if branch.is_default:
            return branch
    return None


def update_branch(branch: Branch) -> Branch:
    branch.synced_at = branch.synced_at.__class__.now()
    _branches[branch.id] = branch
    return branch


def delete_branch(branch_id: str) -> bool:
    branch = _branches.get(branch_id)
    if not branch:
        return False
    _unindex_branch(branch_id)
    return True


def sync_repositories_from_provider(
    workspace_id: str,
    provider_type: ProviderType,
    provider_repos: list[dict[str, Any]],
) -> list[Repository]:
    """Sync repositories from a provider, creating/updating local records."""
    conn = get_provider_connection_by_provider(workspace_id, provider_type)
    if not conn:
        raise ValueError(f"No active {provider_type.value} connection for workspace")

    synced: list[Repository] = []
    for pr in provider_repos:
        # Check if repo already exists
        existing = None
        for repo in get_repositories_for_connection(conn.id):
            if repo.provider_repo_id == str(pr.get("id")):
                existing = repo
                break

        if existing:
            # Update
            existing.name = pr.get("name", existing.name)
            existing.full_name = pr.get("full_name", existing.full_name)
            existing.owner = pr.get("owner", {}).get("login", existing.owner)
            existing.is_private = pr.get("private", existing.is_private)
            existing.default_branch = pr.get("default_branch", existing.default_branch)
            existing.description = pr.get("description")
            existing.primary_language = pr.get("language")
            existing.html_url = pr.get("html_url")
            existing.clone_url = pr.get("clone_url")
            existing.ssh_url = pr.get("ssh_url")
            existing.updated_at = _parse_datetime(pr.get("updated_at"))
            existing.pushed_at = _parse_datetime(pr.get("pushed_at"))
            existing.size_kb = pr.get("size")
            existing.topics = pr.get("topics", [])
            existing.metadata = pr.get("metadata", existing.metadata)
            update_repository(existing)
            synced.append(existing)
        else:
            # Create new
            repo = create_repository(
                workspace_id=workspace_id,
                provider_connection_id=conn.id,
                provider_repo_id=str(pr.get("id")),
                name=pr.get("name", ""),
                full_name=pr.get("full_name", ""),
                owner=pr.get("owner", {}).get("login", ""),
                is_private=pr.get("private", False),
                default_branch=pr.get("default_branch", "main"),
                description=pr.get("description"),
                primary_language=pr.get("language"),
                html_url=pr.get("html_url"),
                clone_url=pr.get("clone_url"),
                ssh_url=pr.get("ssh_url"),
                updated_at=_parse_datetime(pr.get("updated_at")),
                pushed_at=_parse_datetime(pr.get("pushed_at")),
                size_kb=pr.get("size"),
                topics=pr.get("topics", []),
                metadata={k: v for k, v in pr.items() if k not in {"id", "name", "full_name", "owner", "private", "default_branch", "description", "language", "html_url", "clone_url", "ssh_url", "updated_at", "pushed_at", "size", "topics"}},
            )
            synced.append(repo)

    conn.last_synced_at = conn.last_synced_at.__class__.now()
    update_provider_connection(conn)
    return synced


def sync_branches_from_provider(
    repo_id: str,
    provider_branches: list[dict[str, Any]],
) -> list[Branch]:
    """Sync branches from a provider, creating/updating local records."""
    repo = get_repository(repo_id)
    if not repo:
        raise ValueError(f"Repository {repo_id} not found")

    synced: list[Branch] = []
    for pb in provider_branches:
        name = pb.get("name", "")
        commit_sha = pb.get("commit", {}).get("sha", "")
        is_default = name == repo.default_branch
        is_protected = pb.get("protected", False)

        existing = None
        for branch in get_branches_for_repository(repo_id):
            if branch.name == name:
                existing = branch
                break

        if existing:
            existing.commit_sha = commit_sha
            existing.is_default = is_default
            existing.is_protected = is_protected
            existing.metadata = pb.get("metadata", existing.metadata)
            update_branch(existing)
            synced.append(existing)
        else:
            branch = create_branch(
                repository_id=repo_id,
                name=name,
                commit_sha=commit_sha,
                is_default=is_default,
                is_protected=is_protected,
                metadata=pb.get("metadata", {}),
            )
            synced.append(branch)

    return synced


def _parse_datetime(value: str | None) -> Any | None:
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_workspace_store() -> dict[str, Workspace]:
    return _workspaces


def set_workspace_store(store: dict[str, Workspace]) -> None:
    global _workspaces, _workspace_by_owner, _provider_connections, _provider_connections_by_workspace
    global _repositories, _repositories_by_connection, _branches, _branches_by_repo
    _workspaces = store
    _workspace_by_owner = {}
    for w in store.values():
        _workspace_by_owner.setdefault(w.owner_id, set()).add(w.id)
    # Reset dependent stores
    _provider_connections = {}
    _provider_connections_by_workspace = {}
    _repositories = {}
    _repositories_by_connection = {}
    _branches = {}
    _branches_by_repo = {}