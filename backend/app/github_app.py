"""GitHub App installation lifecycle, token minting, and verified webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.github_integration import GitHubIntegration
from app.project_scanning import scan_project
from app.projects import get_project_store

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2026-03-10"
_STATE_TTL_SECONDS = 15 * 60


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_private_key() -> str:
    raw = os.getenv("CODE_SONAR_GITHUB_APP_PRIVATE_KEY", "").strip()
    if raw:
        return raw.replace("\\n", "\n")
    path = os.getenv("CODE_SONAR_GITHUB_APP_PRIVATE_KEY_PATH", "").strip()
    if path:
        return Path(path).expanduser().read_text(encoding="utf-8")
    return ""


@dataclass(frozen=True, slots=True)
class GitHubAppSettings:
    app_id: str
    slug: str
    private_key: str
    webhook_secret: str
    state_secret: str

    @classmethod
    def from_env(cls) -> GitHubAppSettings:
        return cls(
            app_id=os.getenv("CODE_SONAR_GITHUB_APP_ID", "").strip(),
            slug=os.getenv("CODE_SONAR_GITHUB_APP_SLUG", "").strip(),
            private_key=_load_private_key(),
            webhook_secret=os.getenv("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "").strip(),
            state_secret=os.getenv("CODE_SONAR_GITHUB_APP_STATE_SECRET", "").strip(),
        )

    @property
    def install_configured(self) -> bool:
        return bool(self.app_id and self.slug and self.private_key and self.state_secret)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.webhook_secret)


@dataclass(frozen=True, slots=True)
class GitHubInstallationRecord:
    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str
    installed_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubInstallationStore:
    """Persist installation identity only. Installation access tokens are never stored."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-installations.json")
        self._lock = RLock()

    def _load(self) -> list[GitHubInstallationRecord]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [GitHubInstallationRecord(**item) for item in data]

    def _save(self, records: list[GitHubInstallationRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def list(self) -> list[GitHubInstallationRecord]:
        with self._lock:
            return self._load()

    def get(self, installation_id: int) -> GitHubInstallationRecord | None:
        with self._lock:
            return next(
                (item for item in self._load() if item.installation_id == installation_id),
                None,
            )

    def upsert(self, record: GitHubInstallationRecord) -> GitHubInstallationRecord:
        with self._lock:
            records = [
                item for item in self._load() if item.installation_id != record.installation_id
            ]
            records.append(record)
            records.sort(key=lambda item: item.installation_id)
            self._save(records)
        return record

    def remove(self, installation_id: int) -> None:
        with self._lock:
            self._save(
                [item for item in self._load() if item.installation_id != installation_id]
            )


@dataclass(frozen=True, slots=True)
class GitHubWebhookJob:
    job_id: str
    delivery_id: str
    installation_id: int
    project_id: str
    repository_full_name: str
    ref: str
    state: str
    created_at: str
    updated_at: str
    scan_id: str | None = None
    score: int | None = None
    error: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubWebhookJobStore:
    """Persistent status store for webhook-triggered project scans."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-webhook-jobs.json")
        self._lock = RLock()

    def _load(self) -> list[GitHubWebhookJob]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [GitHubWebhookJob(**item) for item in data]

    def _save(self, jobs: list[GitHubWebhookJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in jobs], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def get(self, job_id: str) -> GitHubWebhookJob | None:
        with self._lock:
            return next((item for item in self._load() if item.job_id == job_id), None)

    def enqueue(
        self,
        *,
        delivery_id: str,
        installation_id: int,
        project_id: str,
        repository_full_name: str,
        ref: str,
    ) -> GitHubWebhookJob:
        material = f"{delivery_id}:{project_id}:{ref}"
        job_id = "ghjob_" + hashlib.sha256(material.encode()).hexdigest()[:24]
        now = _utcnow()
        with self._lock:
            jobs = self._load()
            existing = next((item for item in jobs if item.job_id == job_id), None)
            if existing is not None:
                return existing
            job = GitHubWebhookJob(
                job_id=job_id,
                delivery_id=delivery_id,
                installation_id=installation_id,
                project_id=project_id,
                repository_full_name=repository_full_name,
                ref=ref,
                state="queued",
                created_at=now,
                updated_at=now,
            )
            jobs.append(job)
            self._save(jobs)
            return job

    def update(self, job_id: str, **changes: Any) -> GitHubWebhookJob:
        with self._lock:
            jobs = self._load()
            current = next((item for item in jobs if item.job_id == job_id), None)
            if current is None:
                raise LookupError("Webhook job not found")
            updated = replace(current, updated_at=_utcnow(), **changes)
            self._save([updated if item.job_id == job_id else item for item in jobs])
            return updated


@dataclass(frozen=True, slots=True)
class GitHubWebhookDelivery:
    delivery_id: str
    event: str
    action: str
    repository_full_name: str | None
    received_at: str
    outcome: str
    project_id: str | None = None
    job_id: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubWebhookDeliveryStore:
    """Webhook delivery audit trail and replay-protection registry."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "github-webhook-deliveries.json")
        self._lock = RLock()

    def _load(self) -> list[GitHubWebhookDelivery]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [GitHubWebhookDelivery(**item) for item in data]

    def _save(self, records: list[GitHubWebhookDelivery]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(item) for item in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def claim(
        self,
        *,
        delivery_id: str,
        event: str,
        action: str,
        repository_full_name: str | None,
    ) -> bool:
        with self._lock:
            records = self._load()
            if any(item.delivery_id == delivery_id for item in records):
                return False
            records.append(
                GitHubWebhookDelivery(
                    delivery_id=delivery_id,
                    event=event,
                    action=action,
                    repository_full_name=repository_full_name,
                    received_at=_utcnow(),
                    outcome="received",
                )
            )
            self._save(records)
            return True

    def complete(
        self,
        delivery_id: str,
        *,
        outcome: str,
        project_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        with self._lock:
            records = self._load()
            current = next((item for item in records if item.delivery_id == delivery_id), None)
            if current is None:
                return
            updated = replace(
                current,
                outcome=outcome,
                project_id=project_id,
                job_id=job_id,
            )
            self._save(
                [updated if item.delivery_id == delivery_id else item for item in records]
            )

    def list(self, *, limit: int = 50) -> list[GitHubWebhookDelivery]:
        with self._lock:
            return self._load()[-limit:]


class GitHubAppRuntime:
    """Mint short-lived installation tokens without persisting or exposing them."""

    def __init__(
        self,
        *,
        settings: GitHubAppSettings | None = None,
        installations: GitHubInstallationStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or GitHubAppSettings.from_env()
        self.installations = installations or GitHubInstallationStore()
        self.client = client or httpx.Client(timeout=20.0)

    @property
    def configured(self) -> bool:
        return self.settings.install_configured

    def issue_install_state(self) -> str:
        if not self.settings.state_secret:
            raise PermissionError("GitHub App state signing is not configured")
        payload = f"{int(time.time())}.{secrets.token_urlsafe(18)}"
        signature = hmac.new(
            self.settings.state_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payload}.{signature}"

    def verify_install_state(self, state: str) -> bool:
        if not self.settings.state_secret:
            return False
        try:
            timestamp_raw, nonce, supplied = state.split(".", 2)
            timestamp = int(timestamp_raw)
        except (TypeError, ValueError):
            return False
        payload = f"{timestamp_raw}.{nonce}"
        expected = hmac.new(
            self.settings.state_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        age = int(time.time()) - timestamp
        return 0 <= age <= _STATE_TTL_SECONDS and hmac.compare_digest(expected, supplied)

    def install_url(self) -> str:
        if not self.settings.install_configured:
            raise PermissionError("GitHub App installation is not configured")
        query = urlencode({"state": self.issue_install_state()})
        return f"https://github.com/apps/{self.settings.slug}/installations/new?{query}"

    def _app_jwt(self) -> str:
        if not self.settings.install_configured:
            raise PermissionError("GitHub App installation is not configured")
        now = int(time.time())
        encoded = jwt.encode(
            {"iat": now - 30, "exp": now + 9 * 60, "iss": self.settings.app_id},
            self.settings.private_key,
            algorithm="RS256",
        )
        return str(encoded)

    def _app_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._app_jwt()}",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def fetch_and_store_installation(self, installation_id: int) -> GitHubInstallationRecord:
        response = self.client.get(
            f"{_GITHUB_API}/app/installations/{installation_id}",
            headers=self._app_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        account = payload.get("account") or {}
        now = _utcnow()
        existing = self.installations.get(installation_id)
        record = GitHubInstallationRecord(
            installation_id=installation_id,
            account_login=str(account.get("login") or "unknown"),
            account_type=str(account.get("type") or "unknown"),
            repository_selection=str(payload.get("repository_selection") or "selected"),
            installed_at=existing.installed_at if existing else now,
            updated_at=now,
        )
        return self.installations.upsert(record)

    def store_installation_payload(self, payload: dict[str, Any]) -> GitHubInstallationRecord:
        installation_id = int(payload["id"])
        account = payload.get("account") or {}
        now = _utcnow()
        existing = self.installations.get(installation_id)
        return self.installations.upsert(
            GitHubInstallationRecord(
                installation_id=installation_id,
                account_login=str(account.get("login") or "unknown"),
                account_type=str(account.get("type") or "unknown"),
                repository_selection=str(payload.get("repository_selection") or "selected"),
                installed_at=existing.installed_at if existing else now,
                updated_at=now,
            )
        )

    def installation_token(self, installation_id: int) -> str:
        if self.installations.get(installation_id) is None:
            raise LookupError("GitHub App installation is not registered")
        response = self.client.post(
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers=self._app_headers(),
        )
        response.raise_for_status()
        token = str(response.json().get("token") or "")
        if not token:
            raise RuntimeError("GitHub did not return an installation token")
        return token

    def integration_for_installation(self, installation_id: int) -> GitHubIntegration:
        return GitHubIntegration(token=self.installation_token(installation_id), auth_mode="app")

    def verify_webhook_signature(self, body: bytes, signature: str | None) -> bool:
        if not self.settings.webhook_secret or not signature:
            return False
        expected = "sha256=" + hmac.new(
            self.settings.webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


_runtime = GitHubAppRuntime()
_job_store = GitHubWebhookJobStore()
_delivery_store = GitHubWebhookDeliveryStore()
router = APIRouter(prefix="/api/github-app", tags=["github-app"])


def get_github_app_runtime() -> GitHubAppRuntime:
    return _runtime


def set_github_app_runtime(runtime: GitHubAppRuntime) -> None:
    global _runtime
    _runtime = runtime


def get_webhook_job_store() -> GitHubWebhookJobStore:
    return _job_store


def set_webhook_job_store(store: GitHubWebhookJobStore) -> None:
    global _job_store
    _job_store = store


def get_webhook_delivery_store() -> GitHubWebhookDeliveryStore:
    return _delivery_store


def set_webhook_delivery_store(store: GitHubWebhookDeliveryStore) -> None:
    global _delivery_store
    _delivery_store = store


def process_webhook_job(job_id: str) -> None:
    store = get_webhook_job_store()
    job = store.get(job_id)
    if job is None or job.state not in {"queued", "failed"}:
        return
    store.update(job_id, state="running", error=None)
    try:
        project = get_project_store().get(job.project_id)
        if project is None:
            raise LookupError("Project not found")
        integration = get_github_app_runtime().integration_for_installation(job.installation_id)
        repository = integration.get_repository(job.repository_full_name)
        checkout = integration.prepare_checkout(repository)
        if checkout.resolve() != Path(project.local_checkout_path).resolve():
            raise RuntimeError("Managed checkout identity mismatch")
        outcome = scan_project(job.project_id)
        store.update(
            job_id,
            state="completed",
            scan_id=outcome.record.scan_id,
            score=outcome.record.score,
            error=None,
        )
    except Exception as exc:
        store.update(job_id, state="failed", error=type(exc).__name__)


WebhookProcessor = Callable[[str], None]
_processor: WebhookProcessor = process_webhook_job


def get_webhook_processor() -> WebhookProcessor:
    return _processor


def set_webhook_processor(processor: WebhookProcessor) -> None:
    global _processor
    _processor = processor


@router.get("/status")
async def github_app_status() -> dict[str, Any]:
    runtime = get_github_app_runtime()
    installations = runtime.installations.list()
    return {
        "configured": runtime.configured,
        "webhook_configured": runtime.settings.webhook_configured,
        "app_slug": runtime.settings.slug if runtime.configured else None,
        "installation_count": len(installations),
        "installations": [item.to_public_dict() for item in installations],
        "installation_tokens_persisted": False,
        "installation_tokens_exposed": False,
    }


@router.get("/install-url")
async def github_app_install_url() -> dict[str, Any]:
    try:
        install_url = get_github_app_runtime().install_url()
    except PermissionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"install_url": install_url, "state_signed": True}


@router.get("/callback")
async def github_app_callback(
    installation_id: int,
    setup_action: str = "install",
    state: str = "",
) -> dict[str, Any]:
    runtime = get_github_app_runtime()
    if not runtime.verify_install_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired GitHub App install state")
    if setup_action not in {"install", "update"}:
        raise HTTPException(status_code=400, detail="Unsupported GitHub App setup action")
    try:
        installation = runtime.fetch_and_store_installation(installation_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="GitHub App installation lookup failed") from exc
    return {
        "connected": True,
        "installation": installation.to_public_dict(),
        "installation_token_persisted": False,
        "installation_token_exposed": False,
    }


@router.get("/webhook-jobs/{job_id}")
async def github_webhook_job(job_id: str) -> dict[str, Any]:
    job = get_webhook_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Webhook job not found")
    return {"job": job.to_public_dict()}


@router.get("/webhook-deliveries")
async def github_webhook_deliveries() -> dict[str, Any]:
    records = get_webhook_delivery_store().list(limit=50)
    return {"count": len(records), "deliveries": [item.to_public_dict() for item in records]}


@router.post("/webhook", status_code=202)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    runtime = get_github_app_runtime()
    body = await request.body()
    if not runtime.verify_webhook_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")

    delivery_id = request.headers.get("x-github-delivery", "").strip()
    event = request.headers.get("x-github-event", "").strip()
    if not delivery_id or not event:
        raise HTTPException(status_code=400, detail="Missing GitHub webhook headers")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid GitHub webhook payload") from exc

    action = str(payload.get("action") or "")
    repository_payload = payload.get("repository") or {}
    repository_full_name = str(repository_payload.get("full_name") or "") or None
    deliveries = get_webhook_delivery_store()
    if not deliveries.claim(
        delivery_id=delivery_id,
        event=event,
        action=action,
        repository_full_name=repository_full_name,
    ):
        return {"accepted": True, "duplicate": True, "queued": False}

    if event == "installation":
        installation_payload = payload.get("installation") or {}
        try:
            installation_id = int(installation_payload["id"])
        except (KeyError, TypeError, ValueError):
            deliveries.complete(delivery_id, outcome="invalid_installation_event")
            return {"accepted": True, "queued": False, "outcome": "invalid_installation_event"}
        if action == "deleted":
            runtime.installations.remove(installation_id)
            deliveries.complete(delivery_id, outcome="installation_deleted")
            return {"accepted": True, "queued": False, "outcome": "installation_deleted"}
        runtime.store_installation_payload(installation_payload)
        deliveries.complete(delivery_id, outcome="installation_updated")
        return {"accepted": True, "queued": False, "outcome": "installation_updated"}

    if event != "push" or repository_full_name is None:
        deliveries.complete(delivery_id, outcome="ignored_event")
        return {"accepted": True, "queued": False, "outcome": "ignored_event"}

    project = get_project_store().find_by_full_name(repository_full_name)
    if project is None:
        deliveries.complete(delivery_id, outcome="unconnected_repository")
        return {"accepted": True, "queued": False, "outcome": "unconnected_repository"}

    ref = str(payload.get("ref") or "")
    expected_ref = f"refs/heads/{project.default_branch}"
    if ref != expected_ref:
        deliveries.complete(
            delivery_id,
            outcome="ignored_non_default_branch",
            project_id=project.project_id,
        )
        return {"accepted": True, "queued": False, "outcome": "ignored_non_default_branch"}

    try:
        installation_id = int((payload.get("installation") or {})["id"])
    except (KeyError, TypeError, ValueError):
        deliveries.complete(
            delivery_id,
            outcome="missing_installation",
            project_id=project.project_id,
        )
        return {"accepted": True, "queued": False, "outcome": "missing_installation"}

    if (
        project.provider_installation_id is not None
        and project.provider_installation_id != installation_id
    ):
        deliveries.complete(
            delivery_id,
            outcome="installation_mismatch",
            project_id=project.project_id,
        )
        return {"accepted": True, "queued": False, "outcome": "installation_mismatch"}

    if project.provider_installation_id is None:
        project = get_project_store().bind_installation(project.project_id, installation_id)

    job = get_webhook_job_store().enqueue(
        delivery_id=delivery_id,
        installation_id=installation_id,
        project_id=project.project_id,
        repository_full_name=repository_full_name,
        ref=ref,
    )
    deliveries.complete(
        delivery_id,
        outcome="scan_queued",
        project_id=project.project_id,
        job_id=job.job_id,
    )
    background_tasks.add_task(get_webhook_processor(), job.job_id)
    return {
        "accepted": True,
        "queued": True,
        "job_id": job.job_id,
        "project_id": project.project_id,
        "token_persisted": False,
        "token_exposed": False,
    }
