"""Security validators for Code Sonar MVP."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
MAX_REPO_SIZE_BYTES: int = 500 * 1024 * 1024
MAX_FILES_PER_SCAN: int = 10_000
MAX_FILE_READ_TIMEOUT: int = 5
MAX_EVIDENCE_LENGTH: int = 500

SCAN_ROOT_DIR: Path = Path(
    os.environ.get("CODESONAR_SCAN_ROOT", str(Path(tempfile.gettempdir()) / "code-sonar-scans"))
)

EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", "env", ".venv", "virtualenv",
    "dist", "build", "target", "out", "htmlcov", "coverage",
    ".next", ".nuxt", ".output",
    ".smoke-out", ".code-sonar", ".codesonar",
})

GENERATED_FILE_NAMES: frozenset[str] = frozenset({
    ".coverage",
    "coverage.xml",
    "coverage.json",
    "junit.xml",
    "test-results.xml",
})

BINARY_EXTENSIONS: frozenset[str] = frozenset({
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

LOCKFILE_NAMES: frozenset[str] = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lockb", "poetry.lock", "Pipfile.lock", "composer.lock", "Cargo.lock",
    "Gemfile.lock", "pdm.lock", "uv.lock",
})


class RepositoryValidationError(ValueError):
    """Raised when a repository path fails security validation."""


def validate_repo_path(
    raw_path: object,
    scan_root: Path | None = None,
    enforce_root: bool | None = None,
) -> Path:
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

    # Containment is the safe default. The escape hatch is intentionally named
    # and limited to explicit local development use.
    enforce = (
        os.environ.get("CODESONAR_UNSAFE_ALLOW_ANY_SCAN_PATH", "0") != "1"
        if enforce_root is None
        else enforce_root
    )
    if enforce:
        configured_root = Path(
            os.environ.get("CODESONAR_SCAN_ROOT", str(SCAN_ROOT_DIR))
        )
        root = (scan_root or configured_root).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RepositoryValidationError(
                "repository path is outside the allowed scan root "
                + str(root)
                + ": "
                + str(resolved)
            ) from exc
    return resolved


def is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


def is_binary_extension(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXTENSIONS


def is_binary_content(path: Path, sniff_bytes: int = 8192) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(sniff_bytes)
    except OSError:
        return True
    return b"\x00" in chunk


def is_lockfile(path: Path) -> bool:
    return path.name in LOCKFILE_NAMES


def is_excluded_directory(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def is_generated_artifact(path: Path) -> bool:
    """Return True for generated test/coverage/runtime artifacts."""
    return path.name in GENERATED_FILE_NAMES


def is_safe_to_read(path: Path, repo_root: Path) -> bool:
    if is_symlink(path):
        return False
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except (ValueError, OSError):
        return False
    if is_excluded_directory(rel) or is_generated_artifact(rel):
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


def assert_within_scan_limits(file_count: int, total_size: int) -> None:
    if file_count > MAX_FILES_PER_SCAN:
        raise RepositoryValidationError(
            "repository exceeds file limit (" + str(MAX_FILES_PER_SCAN) + ")"
        )
    if total_size > MAX_REPO_SIZE_BYTES:
        raise RepositoryValidationError(
            "repository exceeds size limit (" + str(MAX_REPO_SIZE_BYTES) + " bytes)"
        )


_SECRET_RE: re.Pattern[str] = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def redact_secrets(text: str | None) -> str | None:
    if not text:
        return text
    return _SECRET_RE.sub("[REDACTED]", text)


def truncate_evidence(
    text: str | None,
    max_length: int = MAX_EVIDENCE_LENGTH,
) -> str:
    if text is None:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)] + "..."
