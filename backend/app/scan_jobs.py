"""Asynchronous repository scan jobs.

POST /api/scan-job shallow-clones a GitHub repository into
<scan-root>/workspaces/<job_id>/ (inside the configured CODESONAR_SCAN_ROOT so
path-containment validation accepts it) and then runs the exact same scan
pipeline as POST /api/scan (same analyzers, same scoring engine, same history
store).
Progress is human-readable because the target user is a non-technical vibe
coder: "Reading your files…", "Running 8 checks…", "Tallying your score…".
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.security import SCAN_ROOT_DIR

router = APIRouter(prefix="/api/scan-job", tags=["scan-job"])



# Cloned workspaces live INSIDE the configured scan root so the existing
# path-containment validation (validate_repo_path) accepts them without any
# special-casing. Honors CODESONAR_SCAN_ROOT like everything else.
WORKSPACES_ROOT = SCAN_ROOT_DIR / "workspaces"

_OWNER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")

# (clone_url, branch, destination) -> None. Injectable for tests.
CloneRepo = Callable[[str, str | None, Path], None]


def _default_clone_repo(clone_url: str, branch: str | None, dest: Path) -> None:
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [clone_url, str(dest)]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Repository clone failed: "
            + (completed.stderr.strip() or completed.stdout.strip() or "unknown error")
        )


_clone_repo: CloneRepo = _default_clone_repo


def set_clone_repo(clone: CloneRepo | None) -> None:
    """Override repository cloning; primarily used by tests."""
    global _clone_repo
    if clone is not None:
        _clone_repo = clone


def _github_token_for_request(request: Request) -> str:
    """Return the caller's GitHub OAuth token, or '' when not signed in via GitHub."""
    try:
        from app.oauth import current_user
    except Exception:  # pragma: no cover - defensive
        return ""
    user = current_user(request)
    if user is None or user.provider != "github":
        return ""
    return user.github_access_token


def _parse_repo_input(repo: str) -> str:
    """Normalize 'owner/name' or a repo URL to an https clone URL. Fail closed."""
    text = (repo or "").strip()
    if _OWNER_NAME_RE.match(text):
        return f"https://github.com/{text}.git"
    if text.startswith("https://"):
        parsed = urlparse(text)
        if not parsed.hostname:
            raise ValueError("Repository URL has no host")
        return text
    raise ValueError(
        "Repository must be 'owner/name' or an https:// repository URL"
    )


def _with_token(clone_url: str, token: str) -> str:
    """Embed the OAuth token in the clone URL for private repos (never logged)."""
    if not token:
        return clone_url
    parsed = urlparse(clone_url)
    netloc = f"x-access-token:{token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


@dataclass
class ScanJob:
    job_id: str
    repo: str
    branch: str | None
    status: str = "queued"
    step: str = "Queued — waiting to start…"
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "repo": self.repo,
            "status": self.status,
            "step": self.step,
        }
        if self.progress:
            payload["progress"] = self.progress
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return payload


_jobs: dict[str, ScanJob] = {}
_jobs_lock = threading.RLock()


def get_scan_job(job_id: str) -> ScanJob | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _update_job(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)


def _run_job(job_id: str, clone_url: str, branch: str | None, repo_label: str) -> None:
    """Worker thread: clone, then run the unchanged existing scan pipeline."""
    # Deferred imports avoid a circular import with app.main at module load.
    from datetime import datetime, timezone

    from app.history import build_scan_record, compute_repository_id, display_name
    from app.main import _build_scan_response, get_history_store
    from app.scoring.engine import calculate_score
    from app.security import RepositoryValidationError, validate_repo_path
    from app.services.repository import scan_repository

    dest = WORKSPACES_ROOT / job_id
    try:
        _update_job(job_id, status="running", step="Cloning your repository…", progress=0.1)
        WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
        _clone_repo(clone_url, branch, dest)

        _update_job(job_id, step="Reading your files…", progress=0.3)
        try:
            repo_path = validate_repo_path(dest, scan_root=WORKSPACES_ROOT)
        except RepositoryValidationError as exc:
            raise RuntimeError("Cloned repository failed validation: " + str(exc)) from exc

        _update_job(job_id, step="Running 8 checks…", progress=0.5)
        execution = scan_repository(repo_path)
        if not execution.complete:
            failures = [item.analyzer for item in execution.analyzers if item.status == "failed"]
            raise RuntimeError(
                "Scan incomplete; failed analyzers: " + ", ".join(failures)
            )

        _update_job(job_id, step="Tallying your score…", progress=0.8)
        findings = list(execution.findings)
        scoring_result = calculate_score(findings)
        scanned_at = datetime.now(timezone.utc).isoformat()

        persisted_scan_id: str | None = None
        try:
            record = build_scan_record(
                repository_id=compute_repository_id(repo_path),
                repository_path=display_name(repo_path),
                findings=findings,
                scoring=scoring_result,
                scanned_at=scanned_at,
            )
            get_history_store().append(record)
            persisted_scan_id = record.scan_id
        except Exception:
            pass

        response = _build_scan_response(
            repository_label=repo_label,
            findings=findings,
            scoring_result=scoring_result,
            scanned_at=scanned_at,
            scan_id=persisted_scan_id,
            analyzer_execution=[item.__dict__ for item in execution.analyzers],
        )
        _update_job(
            job_id,
            status="done",
            step="Done — your score is ready.",
            progress=1.0,
            result=response.model_dump(mode="json"),
        )
    except Exception as exc:
        # Never leak the embedded OAuth token into the stored error message.
        message = re.sub(r"x-access-token:[^@]+@", "x-access-token:***@", str(exc))
        _update_job(job_id, status="error", step="Something went wrong.", error=message)
    finally:
        shutil.rmtree(dest, ignore_errors=True)


class ScanJobRequest(BaseModel):
    repo: str = Field(
        min_length=1,
        max_length=500,
        description="'owner/name' or https:// repository URL",
    )
    branch: str | None = Field(default=None, min_length=1, max_length=200)


@router.post("", response_model=dict)
async def create_scan_job(request: Request, body: ScanJobRequest) -> dict[str, str]:
    try:
        clone_url = _parse_repo_input(body.repo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = _github_token_for_request(request)
    job_id = uuid.uuid4().hex
    job = ScanJob(job_id=job_id, repo=body.repo.strip(), branch=body.branch)
    with _jobs_lock:
        _jobs[job_id] = job

    repo_label = body.repo.strip().removesuffix(".git").split("github.com/")[-1]
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, _with_token(clone_url, token), body.branch, repo_label),
        name=f"scan-job-{job_id}",
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@router.get("/{job_id}")
async def scan_job_status(job_id: str) -> dict[str, Any]:
    if not _JOB_ID_RE.match(job_id or ""):
        raise HTTPException(status_code=404, detail="Unknown scan job")
    job = get_scan_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown scan job")
    return job.to_dict()
