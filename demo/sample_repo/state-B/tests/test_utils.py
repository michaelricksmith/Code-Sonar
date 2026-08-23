"""Tests for the demo sample repo (state B).

The ``TODO: ship it`` comment from state A has been removed;
the drift demo will show this as a RESOLVED finding.
"""

from __future__ import annotations

from app.utils import add, greet, multiply


def test_greet_returns_hello_prefix() -> None:
    assert greet("World") == "Hello, World!"


def test_add_basic() -> None:
    assert add(2, 3) == 5


def test_multiply_basic() -> None:
    assert multiply(4, 5) == 20


def test_placeholder() -> None:
    assert True
