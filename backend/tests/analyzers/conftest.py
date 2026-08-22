"""Pytest fixtures for analyzer tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def mixed_repo():
    """Yield a temp dir containing a controllable mix of source and non-source files.

    Layout (line counts based on `small = 1 line`, `big = N lines`):
      tmp/small.py            -> 1 line, under any threshold
      tmp/exact.py            -> configured threshold exactly
      tmp/big.py              -> 1 line over threshold
      tmp/huge.py             -> 2x threshold (ERROR severity)
      tmp/massive.py          -> 3x+ threshold (CRITICAL severity)
      tmp/excluded/.venv/x.py -> inside excluded directory
      tmp/node_modules/y.js   -> inside excluded directory
      tmp/build/out.py        -> inside excluded directory
      tmp/notes.md            -> source extension, under threshold
      tmp/image.png           -> binary extension
    """
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)

        def write_lines(path: Path, n: int) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(f"line {i}" for i in range(n)), encoding="utf-8")
            # Ensure trailing newline so line counts are exact.
            if not path.read_text(encoding="utf-8").endswith("\n"):
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\n")

        write_lines(root / "small.py", 1)
        write_lines(root / "exact.py", 500)
        write_lines(root / "big.py", 501)
        write_lines(root / "huge.py", 1000)
        write_lines(root / "massive.py", 1500)
        write_lines(root / "notes.md", 50)
        write_lines(root / "excluded" / ".venv" / "x.py", 600)
        write_lines(root / "excluded" / "node_modules" / "y.js", 600)
        write_lines(root / "build" / "out.py", 600)
        (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00")

        yield root


@pytest.fixture
def threshold() -> int:
    return 500
