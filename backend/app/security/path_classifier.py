"""Source/test/fixture path classification for deterministic scoring."""

from __future__ import annotations

from typing import Final

FIXTURE_FILENAMES: Final[frozenset[str]] = frozenset({
    ".env.example",
    "example.env",
    "config.example.yaml",
    "config.example.yml",
    "config.example.json",
    "settings.example.json",
    "pytest.ini.example",
    "conftest.example.py",
})

TEST_DIR_NAMES: Final[frozenset[str]] = frozenset({
    "tests",
    "test",
    "tests_",
    "__tests__",
})

FIXTURE_DIR_NAMES: Final[frozenset[str]] = frozenset({
    "fixtures",
    "testdata",
    "test_data",
    "examples",
    "example",
    "example_data",
})

FIXTURE_ROOT_NAMES: Final[frozenset[str]] = frozenset({
    "demo",
    "demos",
    "sample",
    "samples",
    "sample_repo",
})

_TEST_PREFIX: Final[str] = "test_"
_TEST_SUFFIX_PY: Final[str] = "_test.py"
_TEST_SUFFIX_PYI: Final[str] = "_test.pyi"
_CONFTEST: Final[str] = "conftest.py"

SOURCE = "source"
TEST = "test"
FIXTURE = "fixture"


def classify_path(rel_path: str) -> str:
    """Return SOURCE, TEST, or FIXTURE for a repository-relative path."""
    if not rel_path:
        return SOURCE

    normalized = rel_path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return SOURCE
    basename = parts[-1]

    if basename in FIXTURE_FILENAMES:
        return FIXTURE

    # Dedicated top-level demo/sample repositories exist only to exercise the
    # analyzers, so every finding beneath them is fixture context even when the
    # sample repository contains its own tests directory.
    if parts[0] in FIXTURE_ROOT_NAMES:
        return FIXTURE

    if basename == _CONFTEST:
        return TEST
    if basename.startswith(_TEST_PREFIX) and basename.endswith((".py", ".pyi")):
        return TEST
    if basename.endswith((_TEST_SUFFIX_PY, _TEST_SUFFIX_PYI)):
        return TEST

    # A real repository tests/ tree remains test context even when it contains
    # a nested fixtures/ directory. This preserves the historical classifier
    # contract and keeps dashboard source-breakdown semantics stable.
    for part in parts[:-1]:
        if part in TEST_DIR_NAMES:
            return TEST
    for part in parts[:-1]:
        if part in FIXTURE_DIR_NAMES:
            return FIXTURE

    return SOURCE


def is_fixture(rel_path: str) -> bool:
    return classify_path(rel_path) in (TEST, FIXTURE)


def is_test_file(rel_path: str) -> bool:
    return classify_path(rel_path) == TEST
