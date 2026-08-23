"""Source-vs-fixture path classification for Code Sonar scoring.

Distinguishes *production-source* findings from *test-fixture / example*
findings so the scoring engine can apply a context modifier (see
``app.scoring.engine``) without burying real security debt.

This is a pure classification helper. It does **not** suppress any
finding; it returns the context classification that downstream
consumers (scoring, frontend) can use to apply their own policy.

Classification rules (first match wins):

1. Filename-specific overrides — ``.env.example``, ``config.example.*``
   are documented examples and always classified as ``FIXTURE``.
2. Path-pattern — any file whose name starts with ``test_`` or ends
   with ``_test.py`` is a ``TEST`` file.
3. Directory — any file under a ``tests/`` / ``test/`` directory is
   classified as ``TEST``; any file under ``examples/``,
   ``fixtures/``, ``testdata/`` is ``FIXTURE``.
4. Default — ``SOURCE``.

``TEST`` is the stricter subclass: any logic that should suppress on
fixtures should still allow the user to inspect findings on test
files individually. The scoring engine treats both classes
identically today (the modifier is the same); future analyzers may
diverge.
"""

from __future__ import annotations

from typing import Final

#: File basenames that are *always* fixture / example content,
#: regardless of where they live in the tree. These are documentation
#: examples and never contain live secrets or live debt.
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


#: Directory names whose contents are test fixtures.
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


#: Filename patterns (case-sensitive, applied to the basename) that
#: identify a file as a test file even when it is *not* under a test
#: directory.
_TEST_PREFIX: Final[str] = "test_"
_TEST_SUFFIX_PY: Final[str] = "_test.py"
_TEST_SUFFIX_PYI: Final[str] = "_test.pyi"
_CONFTEST: Final[str] = "conftest.py"


#: Public classification values.
SOURCE = "source"
TEST = "test"
FIXTURE = "fixture"


def classify_path(rel_path: str) -> str:
    """Return the classification of a relative path.

    Args:
        rel_path: Forward-slash relative path from the repo root
                  (e.g. ``"tests/test_x.py"``, ``"src/app/main.py"``).

    Returns:
        One of ``SOURCE``, ``TEST``, ``FIXTURE``. ``TEST`` is the
        stricter subclass (used by the scoring engine's test-folder
        modifier) — for the purposes of the source-context modifier,
        ``TEST`` and ``FIXTURE`` are equivalent.
    """
    if not rel_path:
        return SOURCE
    normalized = rel_path.replace("\\", "/")
    parts = normalized.split("/")
    basename = parts[-1]

    # 1. Filename-specific overrides.
    if basename in FIXTURE_FILENAMES:
        return FIXTURE

    # 2. Test-file basename patterns.
    if basename == _CONFTEST:
        return TEST
    if basename.startswith(_TEST_PREFIX) and basename.endswith((".py", ".pyi")):
        return TEST
    if basename.endswith((_TEST_SUFFIX_PY, _TEST_SUFFIX_PYI)):
        return TEST

    # 3. Test / fixture directories.
    for part in parts[:-1]:
        if part in TEST_DIR_NAMES:
            return TEST
        if part in FIXTURE_DIR_NAMES:
            return FIXTURE

    # 4. Default: production source.
    return SOURCE


def is_fixture(rel_path: str) -> bool:
    """True if ``rel_path`` is fixture / test / example content.

    Used by the scoring engine to apply the source-context modifier.
    """
    return classify_path(rel_path) in (TEST, FIXTURE)


def is_test_file(rel_path: str) -> bool:
    """True if ``rel_path`` is a test file (strictly, ``TEST`` class)."""
    return classify_path(rel_path) == TEST
