"""Tests for the demo sample repo (state A).

Intentionally contains a `TODO: ship it` comment so that
``comment_markers:todo`` fires and the dashboard surfaces it as
a finding in the test files section.
"""

from __future__ import annotations

from app.utils import add, greet, multiply


def test_greet_returns_hello_prefix() -> None:
    assert greet("World") == "Hello, World!"


def test_add_basic() -> None:
    assert add(2, 3) == 5


def test_multiply_basic() -> None:
    assert multiply(4, 5) == 20


# TODO: ship it
def test_placeholder() -> None:
    assert True
