"""Remediation worktrees must live inside the scan root.

Regression: production returned "repository path is outside the allowed scan
root" after "Approve & fix this for me" because Git worktrees defaulted to
``~/.code-sonar/remediation-worktrees`` while the validation rescan runs
``scan_repository`` -> ``validate_repo_path`` against the default scan root.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.remediation.cursor import CursorRemediationExecutor
from app.remediation.validation import RemediationValidationService
from app.remediation.workspace import GitWorktreeManager
from app.security import (
    REMEDIATION_WORKTREES_DIR,
    SCAN_ROOT_DIR,
    validate_repo_path,
)


def test_default_worktree_dir_is_inside_scan_root() -> None:
    root = SCAN_ROOT_DIR.expanduser().resolve()
    REMEDIATION_WORKTREES_DIR.expanduser().resolve().relative_to(root)


def _cursor_executor() -> CursorRemediationExecutor:
    return CursorRemediationExecutor(
        command_template=("cursor", "{workspace}", "{instruction}")
    )


def test_all_remediation_roots_agree_on_default() -> None:
    expected = REMEDIATION_WORKTREES_DIR.expanduser().resolve()
    assert GitWorktreeManager().root.expanduser().resolve() == expected
    assert (
        RemediationValidationService().workspace_root.expanduser().resolve()
        == expected
    )
    assert _cursor_executor().workspace_root.expanduser().resolve() == expected


def test_validate_repo_path_accepts_default_worktree_location() -> None:
    probe = REMEDIATION_WORKTREES_DIR / f"probe-{uuid.uuid4().hex}"
    probe.mkdir(parents=True, exist_ok=True)
    try:
        resolved = validate_repo_path(probe)
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    assert resolved == probe.resolve()


def test_no_home_based_worktree_default_remains() -> None:
    for root in (
        GitWorktreeManager().root,
        RemediationValidationService().workspace_root,
        _cursor_executor().workspace_root,
    ):
        assert ".code-sonar" not in Path(root).parts
