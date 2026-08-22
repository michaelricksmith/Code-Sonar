"""Security validators for Code Sonar MVP.

Implements the controls documented in backend/SECURITY.md. Single-file
module on purpose: avoids cross-file import ordering issues and keeps the
security surface easy to audit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
MAX_REPO_SIZE_BYTES: int = 500 * 1024 * 1024
MAX_FILES_PER_SCAN: int = 10_000
MAX_FILE_READ_TIMEOUT: int = 5
MAX_EVIDENCE_LENGTH: int = 500


# Allowlisted scan root. Production deployments should set this (or the
# CODESONAR_SCAN_ROOT env var) to a controlled directory and run with
# CODESONAR_ENFORCE_SCAN_ROOT=1. Tests and the MVP self-scan run without
# the allowlist so they can target temp directories or the workspace.
SCAN_ROOT_DIR: Path = Path(
    os.environ.get("CODESONAR_SCAN_ROOT", "/tmp/code-sonar-scans")
)
_ENFORCE_SCAN_ROOT: bool = os.environ.get("CODESONAR_ENFORCE_SCAN_ROOT", "0") == "1"


EXCLUDED_DIRS: frozenset = frozenset({
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    "venv", "env", ".venv", "virtualenv",
    "dist", "build", "target", "out",
    ".next", ".nuxt", ".output",
})

BINARY_EXTENSIONS: frozenset = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".wasm",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".mov", ".avi", ".mkv",
    ".mp3", ".wav", ".flac",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".lock", ".log", ".tmp", ".swp", ".bak",
    ".pyc", ".pyo", ".class", ".jar",
    ".ttf", ".woff", ".woff2", ".eot",
})


class RepositoryValidationError(ValueError):
    """Raised when a repository path fails security validation."""


def validate_repo_path(raw_path, scan_root=None, enforce_root=None):
    """Validate and resolve a repository path.

    Returns the resolved absolute Path on success. Raises
    RepositoryValidationError on None / empty / non-existent /
    non-directory input, or when the resolved path lies outside the
    allowlisted scan root.
    """
    if raw_path is None:
        raise RepositoryValidationError("repository path is required")
    text = str(raw_path).strip()
    if not text:
        raise RepositoryValidationError("repository path is empty")

    p = Path(text)
    try:
        resolved = p.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RepositoryValidationError(
            "invalid repository path (not found): " + text
        ) from exc

    if not resolved.is_dir():
        raise RepositoryValidationError(
            "invalid repository path (not a directory): " + text
        )

    enforce = _ENFORCE_SCAN_ROOT if enforce_root is None else enforce_root
    if enforce:
        root = (scan_root or SCAN_ROOT_DIR).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RepositoryValidationError(
                "repository path is outside the allowed scan root "
                + str(root) + ": " + str(resolved)
            ) from exc

    return resolved


def is_symlink(path):
    try:
        return path.is_symlink()
    except OSError:
        return False


def is_binary_extension(path):
    return path.suffix.lower() in BINARY_EXTENSIONS


def is_binary_content(path, sniff_bytes=8192):
    try:
        with open(path, "rb") as f:
            chunk = f.read(sniff_bytes)
    except OSError:
        return True
    return b"\x00" in chunk


def is_excluded_directory(path):
    return any(part in EXCLUDED_DIRS for part in path.parts)


def is_safe_to_read(path, repo_root):
    if is_symlink(path):
        return False
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    if is_excluded_directory(rel):
        return False
    if is_binary_extension(path):
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > MAX_FILE_SIZE_BYTES:
        return False
    if size > 0 and is_binary_content(path):
        return False
    return True


def assert_within_scan_limits(file_count, total_size):
    if file_count > MAX_FILES_PER_SCAN:
        raise RepositoryValidationError(
            "repository exceeds file limit (" + str(MAX_FILES_PER_SCAN) + ")"
        )
    if total_size > MAX_REPO_SIZE_BYTES:
        raise RepositoryValidationError(
            "repository exceeds size limit ("
            + str(MAX_REPO_SIZE_BYTES) + " bytes)"
        )


_SECRET_RE = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def redact_secrets(text):
    if not text:
        return text
    return _SECRET_RE.sub("[REDACTED]", text)


def truncate_evidence(text, max_length=MAX_EVIDENCE_LENGTH):
    if text is None:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)] + "..."
