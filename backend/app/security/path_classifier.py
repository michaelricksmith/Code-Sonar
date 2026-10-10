"""Source/test/fixture path classification for deterministic scoring."""

from __future__ import annotations

from typing import Final

FIXTURE_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        ".env.example",
        "example.env",
        "config.example.yaml",
        "config.example.yml",
        "config.example.json",
        "settings.example.json",
        "pytest.ini.example",
        "conftest.example.py",
    }
)

TEST_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "tests",
        "test",
        "tests_",
        "__tests__",
    }
)

FIXTURE_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "fixtures",
        "testdata",
        "test_data",
        "examples",
        "example",
        "example_data",
    }
)

FIXTURE_ROOT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "demo",
        "demos",
        "sample",
        "samples",
        "sample_repo",
    }
)

_TEST_PREFIX: Final[str] = "test_"
_TEST_SUFFIX_PY: Final[str] = "_test.py"
_TEST_SUFFIX_PYI: Final[str] = "_test.pyi"
_CONFTEST: Final[str] = "conftest.py"

SOURCE = "source"
TEST = "test"
FIXTURE = "fixture"


def _normalize_parts(rel_path: str) -> list[str]:
    normalized = rel_path.replace("\\", "/")
    return [part for part in normalized.split("/") if part]


def _is_fixture_basename(basename: str) -> bool:
    return basename in FIXTURE_FILENAMES


def _is_fixture_root(parts: list[str]) -> bool:
    # Dedicated top-level demo/sample repositories exist only to exercise the
    # analyzers, so every finding beneath them is fixture context even when the
    # sample repository contains its own tests directory.
    return parts[0] in FIXTURE_ROOT_NAMES


def _is_test_filename(basename: str) -> bool:
    if basename == _CONFTEST:
        return True
    if basename.startswith(_TEST_PREFIX) and basename.endswith((".py", ".pyi")):
        return True
    return basename.endswith((_TEST_SUFFIX_PY, _TEST_SUFFIX_PYI))


def _has_dir_name(parts: list[str], dir_names: frozenset[str]) -> bool:
    for part in parts[:-1]:
        if part in dir_names:
            return True
    return False


def classify_path(rel_path: str) -> str:
    """Return SOURCE, TEST, or FIXTURE for a repository-relative path."""
    if not rel_path:
        return SOURCE

    parts = _normalize_parts(rel_path)
    if not parts:
        return SOURCE
    basename = parts[-1]

    if _is_fixture_basename(basename):
        return FIXTURE
    if _is_fixture_root(parts):
        return FIXTURE
    if _is_test_filename(basename):
        return TEST

    # A real repository tests/ tree remains test context even when it contains
    # a nested fixtures/ directory. This preserves the historical classifier
    # contract and keeps dashboard source-breakdown semantics stable.
    if _has_dir_name(parts, TEST_DIR_NAMES):
        return TEST
    if _has_dir_name(parts, FIXTURE_DIR_NAMES):
        return FIXTURE

    return SOURCE


def is_fixture(rel_path: str) -> bool:
    return classify_path(rel_path) in (TEST, FIXTURE)


def is_test_file(rel_path: str) -> bool:
    return classify_path(rel_path) == TEST
