"""Small utility module for the Code Sonar private-beta demo (state B).

The ``TODO`` from state A has been removed; this file is now
cleaner. The drift demo will show this as a RESOLVED finding.
"""

from __future__ import annotations


def greet(name: str) -> str:
    """Return a friendly greeting for the given ``name``."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Return the sum of ``a`` and ``b``."""
    return a + b


def multiply(a: int, b: int) -> int:
    return a * b
