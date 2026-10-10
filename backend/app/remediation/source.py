"""Re-materialize the remediation source checkout on demand.

Hosted scans (``POST /api/scan-job``) clone into a per-job workspace that is
deleted when the scan finishes, so the ``repository_path`` persisted on the
scan record no longer exists when the user later approves remediation. This
module bridges that gap:

- When the recorded checkout is still present, it is reused as-is.
- Otherwise the recorded ``repository_slug`` is shallow-cloned (with the
  approving user's GitHub OAuth token for private repositories) into a
  temporary directory inside the configured scan root.
- Temporary clones are removed after the remediation workflow finishes via
  :meth:`RemediationSource.dispose`.

Scan records persisted before slug tracking carry no ``repository_slug``;
for those the source is genuinely unavailable and the original "Remediation
source repository is unavailable" error is preserved.
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.scan_jobs import WORKSPACES_ROOT
from app.security import validate_repo_path
from app.security.git_auth import clone_token, run_git_clone

_TOKEN_RE = re.compile(r"x-access-token:[^@]+@")


@dataclass
class RemediationSource:
    """An on-disk checkout the remediation authorization can bind to.

    Call :meth:`dispose` after the remediation workflow completes. It
    removes temporary re-clones and is a no-op for pre-existing checkouts.
    """

    path: str
    dispose: Callable[[], None]


def _redact_token(message: str) -> str:
    return _TOKEN_RE.sub("x-access-token:***@", message)


def _shallow_clone(clone_url: str, branch: str | None, dest: Path) -> None:
    # The OAuth token (if any) travels via the clone_token context, never in
    # argv, so it stays out of the process table. _redact_token is kept as
    # defense-in-depth for tokens that reach us inside error text.
    try:
        run_git_clone(
            clone_url,
            branch,
            dest,
            failure_prefix="Remediation source clone failed",
        )
    except RuntimeError as exc:
        raise RuntimeError(_redact_token(str(exc))) from exc


def _existing_checkout(repository_path: str) -> Path | None:
    try:
        resolved = Path(repository_path).expanduser().resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


def resolve_remediation_source(
    record: object, *, github_token: str = ""
) -> RemediationSource:
    """Return the on-disk checkout remediation should run against.

    Reuses the recorded checkout when it still exists; otherwise performs a
    shallow clone of the recorded ``repository_slug`` inside the configured
    scan root. Raises ``ValueError("Remediation source repository is
    unavailable")`` when neither is possible (e.g. scan records persisted
    before slug tracking).
    """
    repository_path = getattr(record, "repository_path", "")
    existing = _existing_checkout(str(repository_path)) if repository_path else None
    if existing is not None:
        return RemediationSource(path=str(existing), dispose=lambda: None)

    slug = getattr(record, "repository_slug", None)
    if not slug:
        raise ValueError("Remediation source repository is unavailable")

    branch = getattr(record, "branch", None)
    clone_url = f"https://github.com/{slug}.git"
    WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
    dest = WORKSPACES_ROOT / f"remediation-{uuid.uuid4().hex}"
    try:
        with clone_token(github_token):
            _shallow_clone(clone_url, branch, dest)
        validated = validate_repo_path(dest, scan_root=WORKSPACES_ROOT)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return RemediationSource(
        path=str(validated),
        dispose=lambda: shutil.rmtree(dest, ignore_errors=True),
    )
