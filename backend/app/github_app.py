"""GitHub App installation lifecycle, short-lived tokens, and verified webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2026-03-10"


@dataclass(frozen=True, slots=True)
class GitHubInstallation:
    installation_id: int
    account_login: str
    account_type: str
    installed_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


class InstallationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-installations.json")
        self._lock = RLock()

    def _load(self) -> list[GitHubInstallation]:
        if not self.path.exists():
            return []
        return [GitHubInstallation(**item) for item in json.loads(self.path.read_text("utf-8"))]

    def _save(self, items: list[GitHubInstallation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps([asdict(item) for item in items], indent=2), "utf-8")
        temp.replace(self.path)

    def upsert(self, item: GitHubInstallation) -> None:
        with self._lock:
            items = [x for x in self._load() if x.installation_id != item.installation_id]
            items.append(item)
            self._save(items)

    def remove(self, installation_id: int) -> None:
        with self._lock:
            self._save([x for x in self._load() if x.installation_id != installation_id])

    def list(self) -> list[GitHubInstallation]:
        with self._lock:
            return self._load()


class GitHubAppAuth:
    """Generate GitHub App JWTs and ephemeral installation access tokens."""

    def __init__(self, *, app_id: str | None = None, private_key: str | None = None) -> None:
        self.app_id = app_id if app_id is not None else os.getenv("CODE_SONAR_GITHUB_APP_ID", "")
        raw_key = private_key if private_key is not None else os.getenv("CODE_SONAR_GITHUB_PRIVATE_KEY", "")
        self.private_key = raw_key.replace("\\n", "\n")

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.private_key)

    def app_jwt(self) -> str:
        if not self.configured:
            raise PermissionError("GitHub App credentials are not configured")
        now = int(datetime.now(timezone.utc).timestamp())
        return str(jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.private_key, algorithm="RS256"))

    def installation_token(self, installation_id: int) -> str:
        response = httpx.post(
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.app_jwt()}",
                "X-GitHub-Api-Version": _API_VERSION,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        token = str(response.json().get("token", ""))
        if not token:
            raise RuntimeError("GitHub did not return an installation token")
        return token


_store = InstallationStore()
_auth = GitHubAppAuth()
router = APIRouter(prefix="/api/github-app", tags=["github-app"])


def get_installation_store() -> InstallationStore:
    return _store


def set_installation_store(store: InstallationStore) -> None:
    global _store
    _store = store


def get_github_app_auth() -> GitHubAppAuth:
    return _auth


def verify_webhook_signature(body: bytes, signature: str | None) -> None:
    secret = os.getenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise PermissionError("GitHub webhook secret is not configured")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if signature is None or not hmac.compare_digest(expected, signature):
        raise PermissionError("Invalid GitHub webhook signature")


def _record_installation(payload: dict[str, Any]) -> None:
    installation = payload.get("installation") or {}
    account = installation.get("account") or {}
    installation_id = int(installation.get("id", 0))
    if installation_id <= 0:
        return
    get_installation_store().upsert(
        GitHubInstallation(
            installation_id=installation_id,
            account_login=str(account.get("login", "unknown")),
            account_type=str(account.get("type", "unknown")),
            installed_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _rescan_project(full_name: str) -> None:
    """Refresh the managed checkout and run the existing deterministic project scan."""
    from app.github_integration import GitHubIntegration
    from app.main import scan_project
    from app.projects import get_project_store

    project = next(
        (p for p in get_project_store().list() if f"{p.owner}/{p.name}".lower() == full_name.lower()),
        None,
    )
    if project is None:
        return
    installations = get_installation_store().list()
    if not installations:
        return
    token = get_github_app_auth().installation_token(installations[0].installation_id)
    integration = GitHubIntegration(token=token, auth_mode="app")
    repository = integration.get_repository(full_name)
    integration.prepare_checkout(repository)
    import asyncio

    asyncio.run(scan_project(project.project_id))


@router.get("/status")
async def github_app_status() -> dict[str, Any]:
    installations = get_installation_store().list()
    return {
        "configured": get_github_app_auth().configured,
        "installation_count": len(installations),
        "installations": [item.to_public_dict() for item in installations],
        "private_key_exposed": False,
        "installation_token_persisted": False,
        "webhook_secret_exposed": False,
    }


@router.get("/install-url")
async def github_app_install_url() -> dict[str, Any]:
    slug = os.getenv("CODE_SONAR_GITHUB_APP_SLUG", "").strip()
    if not slug:
        raise HTTPException(status_code=503, detail="GitHub App slug is not configured")
    return {"install_url": f"https://github.com/apps/{slug}/installations/new"}


@router.get("/callback")
async def github_app_callback(installation_id: int) -> dict[str, Any]:
    """Record a completed GitHub App installation without storing an access token."""
    try:
        token = get_github_app_auth().installation_token(installation_id)
        response = httpx.get(
            f"{_GITHUB_API}/installation/repositories",
            headers={"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": _API_VERSION},
            timeout=20.0,
        )
        response.raise_for_status()
    except (PermissionError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail="Could not verify GitHub App installation") from exc
    get_installation_store().upsert(
        GitHubInstallation(installation_id, "verified", "unknown", datetime.now(timezone.utc).isoformat())
    )
    return {"installed": True, "installation_id": installation_id, "token_persisted": False}


@router.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(default="", alias="X-GitHub-Event"),
    x_github_delivery: str = Header(default="", alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    body = await request.body()
    try:
        verify_webhook_signature(body, x_hub_signature_256)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    payload = json.loads(body or b"{}")

    if x_github_event in {"installation", "installation_repositories"}:
        if payload.get("action") == "deleted":
            installation_id = int((payload.get("installation") or {}).get("id", 0))
            if installation_id:
                get_installation_store().remove(installation_id)
        else:
            _record_installation(payload)

    repository = payload.get("repository") or {}
    full_name = str(repository.get("full_name", ""))
    should_rescan = x_github_event == "push" or (
        x_github_event == "pull_request" and payload.get("action") in {"opened", "reopened", "synchronize"}
    )
    if should_rescan and full_name:
        background_tasks.add_task(_rescan_project, full_name)

    return {
        "accepted": True,
        "delivery_id": x_github_delivery,
        "event": x_github_event,
        "rescan_scheduled": bool(should_rescan and full_name),
    }
