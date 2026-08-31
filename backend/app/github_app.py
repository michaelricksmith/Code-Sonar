"""GitHub App authentication, installation state, and webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.github_integration import GitHubIntegration, get_github_integration
from app.projects import get_project_store

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2026-03-10"
_INSTALL_STATE_TTL_SECONDS = 15 * 60
ScanHandler = Callable[[str], Awaitable[Any]]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class GitHubInstallation:
    installation_id: int
    account_login: str
    account_type: str
    installed_at: str
    updated_at: str
    repository_selection: str = "selected"

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

    def get(self, installation_id: int) -> GitHubInstallation | None:
        with self._lock:
            return next(
                (item for item in self._load() if item.installation_id == installation_id),
                None,
            )

    def upsert(self, record: GitHubInstallation) -> GitHubInstallation:
        with self._lock:
            records = [
                item
                for item in self._load()
                if item.installation_id != record.installation_id
            ]
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
    outcome: str = "received"
    job_id: str | None = None


class WebhookAuditStore:
    """Append-style audit store with an atomic delivery claim for replay protection."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-webhooks.jsonl")
        self._lock = RLock()

    def _load(self) -> list[WebhookAuditRecord]:
        if not self.path.exists():
            return []
        records: list[WebhookAuditRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(WebhookAuditRecord(**json.loads(line)))
        return records

    def _save(self, records: list[WebhookAuditRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            "".join(json.dumps(asdict(item), sort_keys=True) + "\n" for item in records),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def has_delivery(self, delivery_id: str) -> bool:
        with self._lock:
            return any(item.delivery_id == delivery_id for item in self._load())

    def claim(self, record: WebhookAuditRecord) -> bool:
        with self._lock:
            records = self._load()
            if any(item.delivery_id == record.delivery_id for item in records):
                return False
            records.append(record)
            self._save(records)
            return True

    def append(self, record: WebhookAuditRecord) -> None:
        with self._lock:
            records = self._load()
            records.append(record)
            self._save(records)

    def update(self, delivery_id: str, **changes: Any) -> WebhookAuditRecord:
        with self._lock:
            records = self._load()
            current = next((item for item in records if item.delivery_id == delivery_id), None)
            if current is None:
                raise LookupError("Webhook delivery not found")
            updated = replace(current, **changes)
            self._save(
                [updated if item.delivery_id == delivery_id else item for item in records]
            )
            return updated

    def list(self, limit: int = 50) -> list[WebhookAuditRecord]:
        with self._lock:
            return self._load()[-limit:]


@dataclass(frozen=True, slots=True)
class WebhookScanJob:
    job_id: str
    delivery_id: str
    project_id: str
    installation_id: int | None
    state: str
    created_at: str
    updated_at: str
    scan_id: str | None = None
    score: int | None = None
    error: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


class WebhookScanJobStore:
    """Persistent status for scans scheduled by verified GitHub deliveries."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-webhook-jobs.json")
        self._lock = RLock()

    def _load(self) -> list[WebhookScanJob]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [WebhookScanJob(**item) for item in payload]

    def _save(self, jobs: list[WebhookScanJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in jobs], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def get(self, job_id: str) -> WebhookScanJob | None:
        with self._lock:
            return next((item for item in self._load() if item.job_id == job_id), None)

    def enqueue(
        self,
        *,
        delivery_id: str,
        project_id: str,
        installation_id: int | None,
    ) -> WebhookScanJob:
        material = f"{delivery_id}:{project_id}"
        job_id = "ghjob_" + hashlib.sha256(material.encode()).hexdigest()[:24]
        now = _utcnow()
        with self._lock:
            jobs = self._load()
            existing = next((item for item in jobs if item.job_id == job_id), None)
            if existing is not None:
                return existing
            job = WebhookScanJob(
                job_id=job_id,
                delivery_id=delivery_id,
                project_id=project_id,
                installation_id=installation_id,
                state="queued",
                created_at=now,
                updated_at=now,
            )
            jobs.append(job)
            self._save(jobs)
            return job

    def update(self, job_id: str, **changes: Any) -> WebhookScanJob:
        with self._lock:
            jobs = self._load()
            current = next((item for item in jobs if item.job_id == job_id), None)
            if current is None:
                raise LookupError("Webhook scan job not found")
            updated = replace(current, updated_at=_utcnow(), **changes)
            self._save([updated if item.job_id == job_id else item for item in jobs])
            return updated


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

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.app_jwt()}",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def installation_details(self, installation_id: int) -> dict[str, Any]:
        response = self.client.get(
            f"{_GITHUB_API}/app/installations/{installation_id}",
            headers=self._headers(),
        )
        response.raise_for_status()
        return dict(response.json())

    def installation_token(self, installation_id: int) -> str:
        response = self.client.post(
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers=self._headers(),
        )
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise RuntimeError("GitHub did not return an installation token")
        return str(token)


_installations = GitHubInstallationStore()
_audit = WebhookAuditStore()
_jobs = WebhookScanJobStore()
_app_auth = GitHubAppAuth()
_scan_handler: ScanHandler | None = None
_active_installation_id: int | None = None
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


def get_webhook_audit_store() -> WebhookAuditStore:
    return _audit


def set_webhook_job_store(store: WebhookScanJobStore) -> None:
    global _jobs
    _jobs = store


def get_webhook_job_store() -> WebhookScanJobStore:
    return _jobs


def set_webhook_scan_handler(handler: ScanHandler) -> None:
    global _scan_handler
    _scan_handler = handler


def set_active_installation_id(installation_id: int | None) -> None:
    global _active_installation_id
    _active_installation_id = installation_id


def get_active_installation_id() -> int | None:
    return _active_installation_id


def _webhook_secret() -> str:
    return os.getenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "")


def _install_state_secret() -> str:
    return os.getenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "")


def _issue_install_state() -> str:
    secret = _install_state_secret()
    if not secret:
        raise PermissionError("GitHub App state signing is not configured")
    payload = f"{int(time.time())}.{secrets.token_urlsafe(18)}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _verify_install_state(state: str) -> bool:
    secret = _install_state_secret()
    if not secret:
        return False
    try:
        timestamp_raw, nonce, supplied = state.split(".", 2)
        timestamp = int(timestamp_raw)
    except (TypeError, ValueError):
        return False
    payload = f"{timestamp_raw}.{nonce}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    age = int(time.time()) - timestamp
    return 0 <= age <= _INSTALL_STATE_TTL_SECONDS and hmac.compare_digest(
        expected, supplied
    )


def _install_url() -> str | None:
    slug = os.getenv("CODE_SONAR_GITHUB_APP_SLUG", "").strip()
    if not slug or not _install_state_secret():
        return None
    query = urlencode({"state": _issue_install_state()})
    return f"https://github.com/apps/{slug}/installations/new?{query}"


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
    installation_id = int(installation["id"])
    account = installation.get("account") or {}
    now = _utcnow()
    existing = get_installation_store().get(installation_id)
    return GitHubInstallation(
        installation_id=installation_id,
        account_login=str(account.get("login") or "unknown"),
        account_type=str(account.get("type") or "unknown"),
        installed_at=existing.installed_at if existing else now,
        updated_at=now,
        repository_selection=str(installation.get("repository_selection") or "selected"),
    )


def _project_for_repository(full_name: str, installation_id: int | None) -> str | None:
    normalized = full_name.lower()
    for project in get_project_store().list():
        if project.provider != "github":
            continue
        if f"{project.owner}/{project.name}".lower() != normalized:
            continue
        if project.provider_installation_id not in {None, installation_id}:
            continue
        return project.project_id
    return None


def _ephemeral_integration(installation_id: int) -> GitHubIntegration:
    token = get_github_app_auth().installation_token(installation_id)
    current = get_github_integration()
    return GitHubIntegration(
        token=token,
        auth_mode="app",
        installation_id=installation_id,
        checkout_root=current.checkout_root,
    )


async def _run_project_scan_job(job_id: str) -> None:
    job_store = get_webhook_job_store()
    job = job_store.get(job_id)
    if job is None or job.state != "queued":
        return
    job_store.update(job_id, state="running", error=None)
    try:
        if _scan_handler is None:
            raise RuntimeError("Webhook scan handler is not configured")
        project = get_project_store().get(job.project_id)
        if project is None:
            raise LookupError("Project not found")
        installation_id = project.provider_installation_id or job.installation_id
        if installation_id is not None:
            integration = _ephemeral_integration(installation_id)
            repository = integration.get_repository(f"{project.owner}/{project.name}")
            checkout = integration.prepare_checkout(repository)
            if checkout.resolve() != Path(project.local_checkout_path).resolve():
                raise RuntimeError("Managed checkout identity mismatch")
        result = await _scan_handler(job.project_id)
        job_store.update(
            job_id,
            state="completed",
            scan_id=getattr(result, "scan_id", None),
            score=getattr(result, "score", None),
            error=None,
        )
    except Exception as exc:
        job_store.update(job_id, state="failed", error=type(exc).__name__)


@router.get("/status")
async def github_app_status() -> dict[str, Any]:
    return {
        "configured": get_github_app_auth().configured,
        "webhook_configured": bool(_webhook_secret()),
        "install_url": _install_url(),
        "installation_count": len(get_installation_store().list()),
        "tokens_persisted": False,
        "tokens_exposed": False,
    }


@router.get("/install-url")
async def github_app_install_url() -> dict[str, Any]:
    try:
        url = _install_url()
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if url is None:
        raise HTTPException(status_code=503, detail="GitHub App install flow is not configured")
    return {"install_url": url, "state_signed": True}


@router.get("/callback")
async def github_app_callback(
    installation_id: int,
    setup_action: str = "install",
    state: str = "",
) -> dict[str, Any]:
    if not _verify_install_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired GitHub App install state")
    if setup_action not in {"install", "update"}:
        raise HTTPException(status_code=400, detail="Unsupported GitHub App setup action")
    try:
        details = get_github_app_auth().installation_details(installation_id)
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="GitHub installation lookup failed") from exc
    account = details.get("account") or {}
    now = _utcnow()
    existing = get_installation_store().get(installation_id)
    record = get_installation_store().upsert(
        GitHubInstallation(
            installation_id=installation_id,
            account_login=str(account.get("login") or "unknown"),
            account_type=str(account.get("type") or "unknown"),
            installed_at=existing.installed_at if existing else now,
            updated_at=now,
            repository_selection=str(details.get("repository_selection") or "selected"),
        )
    )
    set_active_installation_id(installation_id)
    return {
        "connected": True,
        "installation": record.to_public_dict(),
        "token_persisted": False,
        "token_exposed": False,
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
    if get_installation_store().get(installation_id) is None:
        raise HTTPException(status_code=404, detail="GitHub App installation not found")
    try:
        get_github_app_auth().installation_token(installation_id)
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="GitHub installation-token request failed",
        ) from exc
    set_active_installation_id(installation_id)
    return {
        "installation_id": installation_id,
        "active": True,
        "token_persisted": False,
        "token_exposed": False,
    }


@router.get("/webhook-jobs/{job_id}")
async def get_webhook_job(job_id: str) -> dict[str, Any]:
    job = get_webhook_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Webhook scan job not found")
    return {"job": job.to_public_dict()}


@router.get("/webhook-deliveries")
async def get_webhook_deliveries() -> dict[str, Any]:
    records = get_webhook_audit_store().list()
    return {"count": len(records), "deliveries": [asdict(item) for item in records]}


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
    installation_id = installation.installation_id if installation else None
    repository = payload.get("repository") if isinstance(payload, dict) else None
    full_name = str(repository.get("full_name")) if isinstance(repository, dict) else None
    project_id = (
        _project_for_repository(full_name, installation_id) if full_name is not None else None
    )

    audit = WebhookAuditRecord(
        delivery_id=delivery,
        event=event,
        action=str(action) if action is not None else None,
        repository_full_name=full_name,
        installation_id=installation_id,
        project_id=project_id,
        accepted=True,
        scan_triggered=False,
        received_at=_utcnow(),
    )
    if not get_webhook_audit_store().claim(audit):
        return {
            "accepted": True,
            "duplicate": True,
            "delivery_id": delivery,
            "scan_triggered": False,
        }

    if installation is not None:
        if event == "installation" and action == "deleted":
            get_installation_store().remove(installation.installation_id)
            if get_active_installation_id() == installation.installation_id:
                set_active_installation_id(None)
        else:
            get_installation_store().upsert(installation)

    trigger = False
    if project_id is not None and event == "push":
        ref = str(payload.get("ref") or "")
        project = get_project_store().get(project_id)
        trigger = project is not None and ref == f"refs/heads/{project.default_branch}"
    elif project_id is not None and event == "pull_request":
        pull_request = payload.get("pull_request") or {}
        trigger = action == "closed" and bool(pull_request.get("merged"))

    job_id: str | None = None
    if trigger and project_id is not None:
        job = get_webhook_job_store().enqueue(
            delivery_id=delivery,
            project_id=project_id,
            installation_id=installation_id,
        )
        job_id = job.job_id
        get_webhook_audit_store().update(
            delivery,
            scan_triggered=True,
            outcome="scan_queued",
            job_id=job_id,
        )
        background_tasks.add_task(_run_project_scan_job, job_id)
    else:
        outcome = "installation_updated" if event == "installation" else "ignored"
        get_webhook_audit_store().update(delivery, outcome=outcome)

    return {
        "accepted": True,
        "duplicate": False,
        "delivery_id": delivery,
        "event": event,
        "project_id": project_id,
        "scan_triggered": trigger,
        "job_id": job_id,
        "deterministic_score_authority": "code_sonar",
        "token_persisted": False,
        "token_exposed": False,
    }
