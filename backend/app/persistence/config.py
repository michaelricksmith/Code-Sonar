"""Fail-closed persistence configuration and filesystem checks."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.security.runtime import local_dev_enabled

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.stat(), "st_file_attributes", 0) if path.exists() else 0
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass(frozen=True)
class PersistenceConfig:
    database_url: str | None
    data_root: Path

    @property
    def is_postgresql(self) -> bool:
        # Render issues postgres:// URLs; both spellings are PostgreSQL.
        return bool(
            self.database_url
            and (
                self.database_url.startswith("postgresql://")
                or self.database_url.startswith("postgres://")
            )
        )

    @property
    def is_sqlite(self) -> bool:
        return bool(self.database_url and self.database_url.startswith("sqlite"))


def psycopg3_database_url(raw_url: str) -> str:
    """Rewrite a postgres(s) URL to SQLAlchemy's psycopg (v3) dialect.

    The backend ships ``psycopg`` v3 only; SQLAlchemy's default
    ``postgresql://`` dialect imports psycopg2, which is not installed.
    Already-qualified URLs (``postgresql+...://``) pass through untouched.
    """
    if raw_url.startswith("postgresql+"):
        return raw_url
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://") :]
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://") :]
    return raw_url


def persistence_config_from_env() -> PersistenceConfig:
    raw_url = os.environ.get("CODESONAR_DATABASE_URL", "").strip() or None
    root = Path(
        os.environ.get("CODESONAR_DATA_ROOT", str(Path.home() / ".code-sonar"))
    ).expanduser()
    return PersistenceConfig(raw_url, root)


def validate_data_root(root: Path, *, create: bool = True, shared: bool = False) -> Path:
    """Reject link-based roots and restrict newly-created POSIX permissions."""
    if root.exists() and _is_link_or_reparse(root):
        raise RuntimeError("CODESONAR_DATA_ROOT must not be a symlink or reparse point")
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = root.resolve(strict=True)
    if os.name != "nt":
        mode = stat.S_IMODE(resolved.stat().st_mode)
        if mode & 0o077:
            if shared:
                raise RuntimeError("CODESONAR_DATA_ROOT permissions must be 0700 or stricter")
            resolved.chmod(0o700)
    elif shared:
        completed = subprocess.run(
            ["icacls", str(resolved)], capture_output=True, text=True, check=False, timeout=10
        )
        if completed.returncode != 0:
            raise RuntimeError("Unable to verify CODESONAR_DATA_ROOT Windows ACL")
        broad_principals = ("everyone:", "builtin\\users:", "authenticated users:")
        insecure = any(
            any(principal in line.lower() for principal in broad_principals)
            and any(marker in line.lower() for marker in ("(f)", "(m)", "(w)"))
            for line in completed.stdout.splitlines()
        )
        if insecure:
            raise RuntimeError("CODESONAR_DATA_ROOT grants broad Windows write access")
    return resolved


def secure_data_file(path: Path, *, shared: bool = False) -> Path:
    """Reject linked files and enforce owner-only local SQL file permissions."""
    if _is_link_or_reparse(path):
        raise RuntimeError("Persistence files must not be symlinks or reparse points")
    resolved = path.resolve(strict=True)
    if os.name != "nt":
        mode = stat.S_IMODE(resolved.stat().st_mode)
        if mode & 0o077 and shared:
            raise RuntimeError("Persistence file permissions must be 0600 or stricter")
        resolved.chmod(0o600)
    return resolved


def validate_persistence_config(config: PersistenceConfig) -> None:
    if local_dev_enabled():
        if config.database_url and not (config.is_sqlite or config.is_postgresql):
            raise RuntimeError("Unsupported CODESONAR_DATABASE_URL dialect")
        if config.is_sqlite:
            worker_count = max(
                int(os.environ.get("WEB_CONCURRENCY", "1")),
                int(os.environ.get("UVICORN_WORKERS", "1")),
            )
            if worker_count != 1:
                raise RuntimeError("SQLite persistence requires a single local worker")
        validate_data_root(config.data_root)
        return
    if config.database_url is None:
        # No SQL persistence configured: the app runs with ephemeral
        # file/in-memory stores (scan history does not survive restarts).
        # This is a supported production posture for the hosted beta — warn
        # loudly instead of demanding a database the operator never asked for.
        print(
            "WARNING: CODESONAR_DATABASE_URL is not set; running without SQL "
            "persistence. Scan history, projects, and related records are "
            "ephemeral and will not survive a restart. Set "
            "CODESONAR_DATABASE_URL to a PostgreSQL URL for durable storage.",
            file=sys.stderr,
            flush=True,
        )
        validate_data_root(config.data_root)
        return
    if not config.is_postgresql:
        raise RuntimeError("Shared deployments require a PostgreSQL CODESONAR_DATABASE_URL")
    if os.environ.get("CODESONAR_ENCRYPTION_PROVIDER", "").strip() in {"", "local"}:
        raise RuntimeError("Shared deployments require a production encryption provider")
    validate_data_root(config.data_root, shared=True)
