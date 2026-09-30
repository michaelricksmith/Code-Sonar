"""Authenticated ``git clone`` without exposing tokens on the process table.

Embedding an OAuth token in the clone URL (``https://x-access-token:<token>@…``)
leaks the token to every local user via ``ps`` / ``/proc/<pid>/cmdline`` for the
whole clone duration. Instead, the clone URL stays clean and the token travels
through a ``GIT_ASKPASS`` helper script fed from the ``CODE_SONAR_GIT_TOKEN``
environment variable — the same pattern as
``GitHubIntegration._git_authenticated``.

The token is carried in a :class:`contextvars.ContextVar` so worker threads
each see their own value and the 3-argument ``CloneRepo`` injection contract
used by tests stays unchanged.
"""

from __future__ import annotations

import contextvars
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_clone_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "code_sonar_clone_token", default=""
)


_TOKEN_RE = re.compile(r"x-access-token:[^@]+@")


def _redact_token(message: str) -> str:
    """Redact legacy token-bearing URLs from error text (defense in depth)."""
    return _TOKEN_RE.sub("x-access-token:***@", message)


@contextmanager
def clone_token(token: str) -> Iterator[None]:
    """Provide ``token`` to :func:`run_git_clone` for the wrapped block."""
    reset = _clone_token.set(token or "")
    try:
        yield
    finally:
        _clone_token.reset(reset)


def get_clone_token() -> str:
    """Return the clone token active in this context (``""`` when none)."""
    return _clone_token.get()


_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    'case "$1" in\n'
    "  *Username*) printf '%s\\n' \"x-access-token\" ;;\n"
    "  *) printf '%s\\n' \"$CODE_SONAR_GIT_TOKEN\" ;;\n"
    "esac\n"
)


def run_git_clone(
    clone_url: str,
    branch: str | None,
    dest: Path,
    *,
    timeout: int = 600,
    failure_prefix: str = "Repository clone failed",
) -> None:
    """Shallow-clone ``clone_url`` into ``dest``.

    The URL must be clean (no embedded credentials). When a clone token is
    active via :func:`clone_token`, git receives it through ``GIT_ASKPASS`` so
    it never appears in argv, logs, or error messages.
    """
    token = _clone_token.get()
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [clone_url, str(dest)]

    if token:
        with tempfile.TemporaryDirectory(prefix="code-sonar-askpass-") as temp_dir:
            askpass = Path(temp_dir) / "askpass.sh"
            askpass.write_text(_ASKPASS_SCRIPT, encoding="utf-8")
            askpass.chmod(0o700)
            env = os.environ.copy()
            env.update(
                {
                    "GIT_ASKPASS": str(askpass),
                    "GIT_TERMINAL_PROMPT": "0",
                    "CODE_SONAR_GIT_TOKEN": token,
                }
            )
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
    else:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RuntimeError(_redact_token(f"{failure_prefix}: " + detail))
