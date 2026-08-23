"""Pytest fixtures for the security suite."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_repo():
    """Yield a temp dir and create a small mixed-content repo inside.

    Layout:
      tmp/clean.py            -> clean code
      tmp/markers.py          -> TODO + FIXME
      tmp/image.png           -> binary (header + NUL byte)
      tmp/secret.py           -> long high-entropy string
      tmp/.venv/lib.py        -> excluded directory
      tmp/node_modules/j.js   -> excluded directory
      tmp/build/out.py        -> excluded directory
    """
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        (root / "clean.py").write_text("x = 1\n", encoding="utf-8")
        (root / "markers.py").write_text(
            "# TODO: ship it\n# FIXME: later\n", encoding="utf-8"
        )
        (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00")
        (root / "secret.py").write_text(
            "TOKEN = \"abcdefghijklmnopqrstuvwx123456\"\n", encoding="utf-8"
        )
        (root / ".venv").mkdir()
        (root / ".venv" / "lib.py").write_text("# TODO: skipped\n", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "j.js").write_text("// TODO: skipped\n", encoding="utf-8")
        (root / "build").mkdir()
        (root / "build" / "out.py").write_text("# HACK: skipped\n", encoding="utf-8")
        yield root
