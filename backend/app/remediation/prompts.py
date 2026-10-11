"""Prompt-first remediation: grounded fix-prompt generation and copy tracking.

The owner-facing remediation loop is prompt-first:

1. Code Sonar diagnoses a finding.
2. Code Sonar generates a grounded, copyable fix prompt.
3. The user pastes it into their own LLM (Cursor, Claude, ...).
4. That LLM changes the user's real repository.
5. Code Sonar rescans the repository; score/issue deltas verify the change.

The server-side auto-apply machinery (``app/remediation/api.py`` and its
runtime) is PARKED, not deleted: the UI no longer offers it, but the code
stays in place. Only the UI entry point changed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.fix_tracking.models import FixAttempt
from app.fix_tracking.runtime import get_fix_attempt_store

router = APIRouter(prefix="/api/remediation", tags=["remediation"])


# ---------------------------------------------------------------------------
# Data root (same resolution as the other local stores)
# ---------------------------------------------------------------------------


def _data_root() -> Path:
    return Path(os.environ.get("CODESONAR_HOME", str(Path.home()))) / ".code-sonar"


def _prompt_events_path() -> Path:
    return _data_root() / "prompt-events.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_event(event: dict[str, Any]) -> None:
    path = _prompt_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": _utc_now_iso(), **event}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _read_events() -> list[dict[str, Any]]:
    path = _prompt_events_path()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class FindingPayload(BaseModel):
    """Subset of the frontend Finding shape needed to ground a prompt."""

    id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    category: str = ""
    severity: str = ""
    file_path: str = Field(min_length=1)
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    evidence: str = ""
    message: str = ""
    suggestion: str | None = None
    analyzer: str = ""


class FixPromptRequest(BaseModel):
    repository: str = Field(min_length=1)
    scan_id: str | None = None
    finding: FindingPayload


class PromptCopiedRequest(BaseModel):
    scan_id: str | None = None
    repository: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    line_start: int | None = None


# ---------------------------------------------------------------------------
# Deterministic prompt template (no LLM call — cheap and reliable)
# ---------------------------------------------------------------------------


def build_fix_prompt(repository: str, finding: FindingPayload) -> str:
    """Render the grounded fix prompt for one finding.

    Pure function of its inputs: deterministic, no network, no model.
    Written in plain language for a non-technical reader who will paste
    it into their own coding assistant.
    """
    if finding.line_start is not None:
        if finding.line_end is not None and finding.line_end != finding.line_start:
            lines = f" (lines {finding.line_start}-{finding.line_end})"
        else:
            lines = f" (line {finding.line_start})"
    else:
        lines = ""

    evidence = finding.evidence.strip() or "(no code snippet available)"
    suggestion = (finding.suggestion or "").strip()
    if suggestion:
        requested_change = suggestion
    else:
        requested_change = (
            "Fix the issue described above in the smallest reasonable way. "
            "If you are unsure which change is right, explain the options "
            "before changing anything."
        )

    analyzer = finding.analyzer.strip() or "code check"
    symbol = f" In or near `{finding.symbol}`." if finding.symbol else ""

    return f"""Fix this code issue in {repository}

Code Sonar scanned your repository "{repository}" and found an issue:

File: {finding.file_path}{lines}.{symbol}
Issue: {finding.message}
Rule: {finding.rule_id} (found by the {analyzer} check)

The code in question:
```
{evidence}
```

What to change:
{requested_change}

Rules for the fix — follow these exactly:
- Change ONLY what is needed to fix this one issue. Do not refactor or "clean up" unrelated code.
- Do not change how the rest of the app behaves.
- Do not add new libraries or dependencies unless the fix truly requires it.
- Keep the code style consistent with the surrounding code.

When you are done:
1. Run the repository's tests (and its build, if it has one) and make sure everything still passes.
2. Re-scan the repository with Code Sonar to verify the issue is gone and the score improved.

If anything is unclear, ask me before making a bigger change."""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/fix-prompt")
async def generate_fix_prompt(request: FixPromptRequest) -> dict[str, Any]:
    """Generate a deterministic, copyable fix prompt for one finding."""
    prompt = build_fix_prompt(request.repository, request.finding)
    _append_event(
        {
            "event": "generated",
            "repository": request.repository,
            "scan_id": request.scan_id,
            "finding_id": request.finding.id,
            "rule_id": request.finding.rule_id,
            "file_path": request.finding.file_path,
            "line_start": request.finding.line_start,
        }
    )
    return {"prompt": prompt}


@router.post("/prompt-copied")
async def log_prompt_copied(
    http_request: Request, request: PromptCopiedRequest
) -> dict[str, Any]:
    """Record that the user copied a fix prompt (a "fix in progress").

    Persisted durably with the user's identity so verified fixes can be
    attributed per user for reports, streaks, and the weekly digest.
    """
    from app.history.repository_identity import compute_repository_id_for_slug
    from app.oauth import current_user

    user = current_user(http_request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to track fix prompts")
    attempt = FixAttempt.new(
        user_id=user.id,
        repository_id=compute_repository_id_for_slug(request.repository),
        finding_id=request.finding_id,
        rule_id=request.rule_id,
        file_path=request.file_path,
        scan_id=request.scan_id,
    )
    get_fix_attempt_store().append(attempt)
    return {"ok": True, "attempt_id": attempt.attempt_id}


def _resolve_latest_record(store: Any, repository: str, repository_id: str) -> Any:
    """Newest scan record, with a slug-match fallback."""
    latest_record = store.latest(repository_id)
    if latest_record is None:
        # Fall back to a slug match in case the scan was recorded under a
        # different identity scheme (e.g. local-path scans).
        wanted = repository.strip().lower()
        candidates = [
            r
            for r in store.load_all()
            if str(getattr(r, "repository_slug", "") or "").lower() == wanted
        ]
        if candidates:
            latest_record = max(candidates, key=lambda r: str(r.scanned_at))
    return latest_record


def _latest_scan_index(latest_record: Any) -> tuple[str, set[tuple[str, str]]]:
    """Scanned-at timestamp plus the ``(rule_id, file_path)`` finding keys."""
    if latest_record is None:
        return "", set()
    latest_findings: set[tuple[str, str]] = set()
    for snapshot in latest_record.findings or []:
        latest_findings.add(
            (str(snapshot.rule_id or ""), str(snapshot.file_path or ""))
        )
    return str(latest_record.scanned_at or ""), latest_findings


@router.get("/prompt-status")
async def prompt_status(
    http_request: Request, repository: str = Query(min_length=1)
) -> dict[str, Any]:
    """Reconcile copied prompts against the latest scan for a repository.

    Each copied prompt is matched to the latest scan by
    ``(rule_id, file_path)``:

    - ``in_progress`` — no scan has run since the prompt was copied.
    - ``resolved`` — a newer scan ran and the finding is gone.
    - ``still_open`` — a newer scan ran and the finding is still there.
    """
    from app.history.repository_identity import compute_repository_id_for_slug
    from app.main import get_history_store
    from app.oauth import current_user

    user = current_user(http_request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to view prompt status")

    repository_id = compute_repository_id_for_slug(repository)
    attempts = [
        a
        for a in get_fix_attempt_store().list_by_user(user.id)
        if a.repository_id == repository_id
    ]
    latest_copy: dict[tuple[str, str], FixAttempt] = {}
    for attempt in attempts:
        key = attempt.finding_key
        if key not in latest_copy or attempt.copied_at > latest_copy[key].copied_at:
            latest_copy[key] = attempt

    store = get_history_store()
    latest_record = _resolve_latest_record(store, repository, repository_id)
    latest_scanned_at, latest_findings = _latest_scan_index(latest_record)

    items: list[dict[str, Any]] = []
    for (rule_id, file_path), attempt in sorted(
        latest_copy.items(), key=lambda kv: kv[1].copied_at, reverse=True
    ):
        if attempt.verified:
            status = "resolved"
        elif not latest_record or latest_scanned_at <= attempt.copied_at:
            status = "in_progress"
        elif (rule_id, file_path) in latest_findings:
            status = "still_open"
        else:
            status = "resolved"
        items.append(
            {
                "finding_id": attempt.finding_id,
                "rule_id": rule_id,
                "file_path": file_path,
                "status": status,
                "copied_at": attempt.copied_at,
            }
        )
    return {"repository": repository, "items": items}
