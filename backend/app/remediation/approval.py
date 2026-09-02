"""Server-owned, signed, expiring, single-use remediation authorization."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock


@dataclass(frozen=True, slots=True)
class RemediationAuthorization:
    authorization_id: str
    request_id: str
    repository_path: str
    scan_id: str
    finding_id: str
    plan_id: str
    base_commit: str
    executor: str
    remediation_kind: str
    instruction: str
    expires_at: float
    signature: str

    def signing_material(self) -> str:
        return "|".join(
            (
                self.authorization_id,
                self.request_id,
                self.repository_path,
                self.scan_id,
                self.finding_id,
                self.plan_id,
                self.base_commit,
                self.executor,
                self.remediation_kind,
                self.instruction,
                str(self.expires_at),
            )
        )


class RemediationAuthorizationService:
    """Mint and consume capabilities that callers cannot alter or replay."""

    def __init__(self, *, secret: str | None = None, ttl_seconds: float = 300.0) -> None:
        configured = secret or os.environ.get("CODESONAR_REMEDIATION_APPROVAL_SECRET", "")
        self._secret = (configured.encode("utf-8") if configured else secrets.token_bytes(32))
        self.ttl_seconds = ttl_seconds
        self._consumed: set[str] = set()
        self._lock = RLock()

    def issue(
        self,
        *,
        request_id: str,
        repository_path: str,
        scan_id: str,
        finding_id: str,
        plan_id: str,
        executor: str,
        remediation_kind: str,
        instruction: str,
        now: float | None = None,
    ) -> RemediationAuthorization:
        try:
            repository = Path(repository_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError("Remediation source repository is unavailable") from exc
        base_commit = _git_head(repository)
        issued_at = time.time() if now is None else now
        unsigned = RemediationAuthorization(
            authorization_id="auth_" + secrets.token_hex(16),
            request_id=request_id,
            repository_path=str(repository),
            scan_id=scan_id,
            finding_id=finding_id,
            plan_id=plan_id,
            base_commit=base_commit,
            executor=executor,
            remediation_kind=remediation_kind,
            instruction=instruction,
            expires_at=issued_at + self.ttl_seconds,
            signature="",
        )
        return replace(unsigned, signature=self._sign(unsigned.signing_material()))

    def consume(
        self, authorization: RemediationAuthorization, *, now: float | None = None
    ) -> None:
        expected = self._sign(authorization.signing_material())
        if not hmac.compare_digest(expected, authorization.signature):
            raise PermissionError("Remediation authorization signature is invalid")
        current_time = time.time() if now is None else now
        if current_time >= authorization.expires_at:
            raise PermissionError("Remediation authorization has expired")
        with self._lock:
            if authorization.authorization_id in self._consumed:
                raise PermissionError("Remediation authorization has already been used")
            if _git_head(Path(authorization.repository_path)) != authorization.base_commit:
                raise PermissionError("Repository changed after remediation approval")
            self._consumed.add(authorization.authorization_id)

    def _sign(self, material: str) -> str:
        return hmac.new(self._secret, material.encode("utf-8"), hashlib.sha256).hexdigest()


def _git_head(repository: Path) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    head = completed.stdout.strip()
    if completed.returncode != 0 or not head:
        raise ValueError("Remediation source is not a valid Git repository")
    return head
