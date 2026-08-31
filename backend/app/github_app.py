"""GitHub App authentication, installation state, and webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Awaitable, Callable

import httpx
import jwt
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.github_integration import GitHubIntegration, get_github_integration, set_github_integration
from app.projects import get_project_store

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2026-03-10"
ScanHandler = Callable[[str], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class GitHubInstallation:
    installation_id: int
    account_login: str
    account_type: str
    installed_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubInstallationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-installations.json")
        self._lock = RLock()

    def _load(self) -> list[GitHubInstallation]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [GitHubInstallation(**item) for item in payload]

    def _save(self, records: list[GitHubInstallation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def list(self) -> list[GitHubInstallation]:
        with self._lock:
            return self._load()

    def upsert(self, record: GitHubInstallation) -> GitHubInstallation:
        with self._lock:
            records = [item for item in self._load() if item.installation_id != record.installation_id]
            records.append(record)
            records.sort(key=lambda item: item.installation_id)
            self._save(records)
        return record

    def remove(self, installation_id: int) -> None:
        with self._lock:
            records = [item for item in self._load() if item.installation_id != installation_id]
            self._save(records)


@dataclass(frozen=True, slots=True)
class WebhookAuditRecord:
    delivery_id: str
    event: str
    action: str | None
    repository_full_name: str | None
    installation_id: int | None
    project_id: str | None
    accepted: bool
    scan_triggered: bool
    received_at: str


class WebhookAuditStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-webhooks.jsonl")
        self._lock = RLock()

    def append(self, record: WebhookAuditRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


class GitHubAppAuth:
    """Mint short-lived GitHub App installation tokens without persisting them."""

    def __init__(
        self,
        *,
        app_id: str | None = None,
        private_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.app_id = app_id if app_id is not None else os.getenv("CODE_SONAR_GITHUB_APP_ID", "")
        self.private_key = (
            private_key
            if private_key is not None
            else os.getenv("CODE_SONAR_GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
        )
        self.client = client or httpx.Client(timeout=20.0)

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.private_key)

    def app_jwt(self) -> str:
        if not self.configured:
            raise PermissionError("GitHub App credentials are not configured")
        now = datetime.now(timezone.utc)
        payload = {
            "iat": int((now - timedelta(seconds=30)).timestamp()),
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": self.app_id,
        }
        return str(jwt.encode(payload, self.private_key, algorithm="RS256"))

    def installation_token(self, installation_id: int) -> str:
        response = self.client.post(
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.app_jwt()}",
                "X-GitHub-Api-Version": _API_VERSION,
            },
        )
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise RuntimeError("GitHub did not return an installation token")
        return str(token)


_installations = GitHubInstallationStore()
_audit = WebhookAuditStore()
_app_auth = GitHubAppAuth()
_scan_handler: ScanHandler | None = None
router = APIRouter(prefix="/api/github-app", tags=["github-app"])


def set_github_app_auth(auth: GitHubAppAuth) -> None:
    global _app_auth
    _app_auth = auth


def get_github_app_auth() -> GitHubAppAuth:
    return _app_auth


def set_installation_store(store: GitHubInstallationStore) -> None:
    global _installations
    _installations = store


def get_installation_store() -> GitHubInstallationStore:
    return _installations


def set_webhook_audit_store(store: WebhookAuditStore) -> None:
    global _audit
    _audit = store


def set_webhook_scan_handler(handler: ScanHandler) -> None:
    global _scan_handler
    _scan_handler = handler


def _webhook_secret() -> str:
    return os.getenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "")


def _verify_signature(body: bytes, signature: str | None) -> None:
    secret = _webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub webhook secret is not configured")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing GitHub webhook signature")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")


def _installation_from_payload(payload: dict[str, Any]) -> GitHubInstallation | None:
    installation = payload.get("installation")
    if not isinstance(installation, dict) or "id" not in installation:
        return None
    account = installation.get("account") or {}
    now = datetime.now(timezone.utc).isoformat()
    return GitHubInstallation(
        installation_id=int(installation["id"]),
        account_login=str(account.get("login") or "unknown"),
        account_type=str(account.get("type") or "unknown"),
        installed_at=now,
        updated_at=now,
    )


def _project_for_repository(full_name: str) -> str | None:
    normalized = full_name.lower()
    for project in get_project_store().list():
        if project.provider == "github" and f"{project.owner}/{project.name}".lower() == normalized:
            return project.project_id
    return None


async def _run_project_scan(project_id: str) -> None:
    if _scan_handler is not None:
        await _scan_handler(project_id)


@router.get("/status")
async def github_app_status() -> dict[str, Any]:
    return {
        "configured": get_github_app_auth().configured,
        "webhook_configured": bool(_webhook_secret()),
        "installation_count": len(get_installation_store().list()),
        "tokens_persisted": False,
        "tokens_exposed": False,
    }


@router.get("/installations")
async def list_installations() -> dict[str, Any]:
    records = get_installation_store().list()
    return {
        "count": len(records),
        "installations": [item.to_public_dict() for item in records],
        "tokens_exposed": False,
    }


@router.post("/installations/{installation_id}/activate")
async def activate_installation(installation_id: int) -> dict[str, Any]:
    try:
        token = get_github_app_auth().installation_token(installation_id)
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="GitHub installation-token request failed") from exc

    current = get_github_integration()
    set_github_integration(
        GitHubIntegration(
            token=token,
            auth_mode="app",
            checkout_root=current.checkout_root,
        )
    )
    return {
        "installation_id": installation_id,
        "active": True,
        "token_persisted": False,
        "token_exposed": False,
    }


@router.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, Any]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid GitHub webhook payload") from exc

    event = x_github_event or "unknown"
    delivery = x_github_delivery or hashlib.sha256(body).hexdigest()[:24]
    action = payload.get("action") if isinstance(payload, dict) else None
    installation = _installation_from_payload(payload)
    if installation is not None:
        if event == "installation" and action == "deleted":
            get_installation_store().remove(installation.installation_id)
        else:
            get_installation_store().upsert(installation)

    repository = payload.get("repository") if isinstance(payload, dict) else None
    full_name = str(repository.get("full_name")) if isinstance(repository, dict) else None
    project_id = _project_for_repository(full_name) if full_name else None

    trigger = False
    if project_id is not None and event == "push":
        ref = str(payload.get("ref") or "")
        project = get_project_store().get(project_id)
        trigger = project is not None and ref == f"refs/heads/{project.default_branch}"
    elif project_id is not None and event == "pull_request":
        trigger = action in {"closed"} and bool((payload.get("pull_request") or {}).get("merged"))

    if trigger:
        background_tasks.add_task(_run_project_scan, project_id)

    _audit.append(
        WebhookAuditRecord(
            delivery_id=delivery,
            event=event,
            action=str(action) if action is not None else None,
            repository_full_name=full_name,
            installation_id=installation.installation_id if installation else None,
            project_id=project_id,
            accepted=True,
            scan_triggered=trigger,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    return {
        "accepted": True,
        "delivery_id": delivery,
        "event": event,
        "project_id": project_id,
        "scan_triggered": trigger,
        "deterministic_score_authority": "code_sonar",
    }
