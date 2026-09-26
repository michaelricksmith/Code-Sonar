"""Deterministic repository identity.

The repository identity is a stable, derived string that uniquely
identifies a repository on disk without depending on environment,
hostname, or scan timestamp. Two scans of the same repository MUST
produce the same identity; two scans of different repositories MUST
produce different identities.

Algorithm:

1. Resolve the path to an absolute, canonical form (``Path.resolve``).
2. On Windows, normalize the drive-letter prefix to lower-case and
   replace backslashes with forward slashes (Windows paths are
   case-insensitive but case-preserving — lower-casing the prefix
   removes the drive-letter ambiguity that broke prior test runs).
3. Hash the normalized path with SHA-256 and return the first 16
   hex characters.

The hash ensures:

- No filesystem path leaks into the persistence layer (defense in
  depth for secret-bearing paths).
- Stable across rename of intermediate symlinks (the resolved path
  is canonical).

The friendly ``display_name`` (used by the API) is the path's
forward-slash, lower-cased form for human-readability in the
dashboard.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def _canonicalize_path(path: Path) -> str:
    """Return a forward-slash, lower-cased canonical path string."""
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    s = str(resolved).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        # Windows drive letter: lower-case it for stability.
        s = s[0].lower() + s[1:]
    return s


def compute_repository_id(path: Path) -> str:
    """Return a stable 16-char hex repository identity for ``path``.

    Same path → same identity. Different paths → different identities.
    The hash is sha256-derived so no filesystem path is embedded in
    the persisted record.
    """
    canonical = _canonicalize_path(path)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:16]


def compute_repository_id_for_slug(slug: str) -> str:
    """Return a stable 16-char hex repository identity for a repo slug.

    Hosted scans run in a throwaway per-job workspace, so hashing the
    workspace path would give every scan its own identity and history
    would never accumulate. The ``owner/name`` slug is stable across
    scans of the same repository, so it is the right identity key for
    hosted scan history. Normalized (trimmed, lower-cased) so
    ``Owner/Name`` and ``owner/name`` resolve to the same history.
    """
    canonical = slug.strip().lower()
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:16]


def display_name(path: Path) -> str:
    """Return a human-readable path for API responses."""
    return _canonicalize_path(path)
