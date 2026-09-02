"""Security invariants for server-owned remediation capabilities."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from app.remediation.approval import RemediationAuthorizationService


def _repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    (path / "source.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "source.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "base"], check=True)
    return path


def _issue(service: RemediationAuthorizationService, repository: Path, *, now: float = 10.0):
    return service.issue(
        request_id="request-1",
        repository_path=str(repository),
        scan_id="scan-1",
        finding_id="finding-1",
        plan_id="plan-1",
        executor="cursor",
        remediation_kind="approved_patch",
        instruction="Fix only the grounded finding.",
        now=now,
    )


def test_authorization_is_signed_expiring_and_single_use(tmp_path: Path) -> None:
    service = RemediationAuthorizationService(secret="test-secret", ttl_seconds=30)
    authorization = _issue(service, _repository(tmp_path / "repo"))

    service.consume(authorization, now=20)
    with pytest.raises(PermissionError, match="already been used"):
        service.consume(authorization, now=20)

    fresh = _issue(service, Path(authorization.repository_path), now=40)
    with pytest.raises(PermissionError, match="expired"):
        service.consume(fresh, now=71)


def test_authorization_rejects_tampering_and_repository_drift(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "repo")
    service = RemediationAuthorizationService(secret="test-secret")
    authorization = _issue(service, repository)

    with pytest.raises(PermissionError, match="signature"):
        service.consume(replace(authorization, finding_id="attacker-finding"), now=20)

    (repository / "source.py").write_text("value = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "source.py"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-q", "-m", "changed"], check=True)
    with pytest.raises(PermissionError, match="changed after"):
        service.consume(authorization, now=20)
