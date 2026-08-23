"""Small utility module for the Code Sonar private-beta demo (state A).

This module intentionally contains a `TODO` comment so that
``comment_markers:todo`` will fire and the user can see how the
dashboard surfaces it.
"""

from __future__ import annotations


def greet(name: str) -> str:
    """Return a friendly greeting for the given ``name``."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Return the sum of ``a`` and ``b``."""
    return a + b


def multiply(a: int, b: int) -> int:
    # TODO: add overflow check for very large ints
    return a * b
