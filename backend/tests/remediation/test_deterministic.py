"""Unit tests for ``app.remediation.deterministic``.

This is the dedicated test file for the deterministic remediation executor
(the no-AI executor that splits oversized TS/JS files at export boundaries).

Existing related coverage:
- ``tests/remediation/test_cursor_runtime.py`` only checks that the runtime
  wires ``DeterministicRemediationExecutor`` (an ``isinstance`` assertion).
- ``tests/api/test_remediation_api.py`` and ``test_orchestration.py`` exercise
  the broader remediation pipeline, not this module's transforms.

Gaps this file covers:
- ``_parse_instruction``: valid instruction, garbage input, missing period.
- ``_split_typescript``: block kinds/names, empty input, header capture,
  anonymous default exports.
- ``_sanitize_filename``: special characters, all-invalid input.
- ``_split_oversized_file``: missing file, unsupported suffix, fewer than
  two exports, happy-path file layout and barrel content, name collisions.
- ``DeterministicRemediationExecutor.execute``: unapproved request,
  unparseable instruction, unsupported rule, happy path, ValueError path,
  OSError path.
"""

from __future__ import annotations

import pytest

from app.remediation import deterministic as det
from app.remediation.contracts import (
    RemediationExecutionState,
    RemediationRequest,
)
from app.remediation.deterministic import (
    SUPPORTED_RULES,
    DeterministicRemediationExecutor,
    _Block,
    _parse_instruction,
    _sanitize_filename,
    _split_oversized_file,
    _split_typescript,
)


def _ts_two_exports() -> str:
    return "\n".join([
        'import { x } from "./x";',
        "// header comment",
        "",
        "const helper = 3;",
        "",
        "export const alpha = 1;",
        "export function beta() {",
        "  return x + 1;",
        "}",
        "",
    ])


def _instruction(rule_id: str, file_path: str) -> str:
    return f"Resolve Code Sonar finding f-1 ({rule_id}) in {file_path}."


def _mk_request(repo_root, instruction: str, approved: bool = True) -> RemediationRequest:
    return RemediationRequest(
        request_id="req-1",
        repository_path=str(repo_root),
        finding_id="f-1",
        scan_id="scan-1",
        instruction=instruction,
        approved=approved,
    )


@pytest.fixture
def repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.ts").write_text(_ts_two_exports(), encoding="utf-8")
    return tmp_path


# --- Module surface --------------------------------------------------------


def test_supported_rules_contains_oversized():
    assert "oversized_files:over-threshold" in SUPPORTED_RULES
    assert "foo:bar" not in SUPPORTED_RULES


def test_executor_name():
    assert DeterministicRemediationExecutor().executor_name == "deterministic"


def test_block_dataclass():
    block = _Block(name="alpha", kind="export", text="export const alpha = 1;\n")
    assert block.name == "alpha"
    assert block.kind == "export"
    assert block.text == "export const alpha = 1;\n"


# --- _parse_instruction ----------------------------------------------------


def test_parse_instruction_valid():
    parsed = _parse_instruction(
        _instruction("oversized_files:over-threshold", "src/big.ts")
    )
    assert parsed == ("oversized_files:over-threshold", "src/big.ts")


def test_parse_instruction_garbage_returns_none():
    assert _parse_instruction("please fix this file") is None


def test_parse_instruction_missing_trailing_period_returns_none():
    assert _parse_instruction(
        "Resolve Code Sonar finding f-1 (oversized_files:over-threshold) in src/big.ts"
    ) is None


# --- _split_typescript ------------------------------------------------------


def test_split_typescript_blocks():
    blocks = _split_typescript(_ts_two_exports())
    assert [b.kind for b in blocks] == ["internal", "export", "export"]
    assert [b.name for b in blocks] == ["internal_0", "alpha", "beta"]


def test_split_typescript_empty_input():
    assert _split_typescript("") == []


def test_split_typescript_captures_header():
    _split_typescript(_ts_two_exports())
    assert 'import { x } from "./x";' in det._split_typescript.header
    assert det._split_typescript.body_start == 3


def test_split_typescript_anonymous_default_export_name():
    blocks = _split_typescript("export default function() {\n}\n")
    assert blocks[0].name == "export_0"
    assert blocks[0].kind == "export"


# --- _sanitize_filename -----------------------------------------------------


def test_sanitize_filename_special_chars():
    assert _sanitize_filename("foo bar/baz!") == "foo-bar-baz"


def test_sanitize_filename_all_invalid_falls_back():
    assert _sanitize_filename("!!!") == "block"


def test_sanitize_filename_collapses_dashes():
    assert _sanitize_filename("a--b__c") == "a-b__c"


# --- _split_oversized_file --------------------------------------------------


def test_split_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="File not found"):
        _split_oversized_file(tmp_path, "src/nope.ts")


def test_split_unsupported_suffix_raises(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.py").write_text("def a():\n    pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not yet supported"):
        _split_oversized_file(tmp_path, "src/big.py")


def test_split_single_export_raises(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "tiny.ts").write_text("export const a = 1;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fewer than 2"):
        _split_oversized_file(tmp_path, "src/tiny.ts")


def test_split_happy_path_changed_files(repo):
    changed, summary = _split_oversized_file(repo, "src/big.ts")
    assert set(changed) == {
        "src/big_split/alpha.ts",
        "src/big_split/beta.ts",
        "src/big_split/_internal.ts",
        "src/big.ts",
    }
    assert "big_split" in summary


def test_split_happy_path_barrel_content(repo):
    _split_oversized_file(repo, "src/big.ts")
    barrel = (repo / "src" / "big.ts").read_text(encoding="utf-8")
    assert "export { alpha } from './big_split/alpha';" in barrel
    assert "export { beta } from './big_split/beta';" in barrel


def test_split_happy_path_export_files(repo):
    _split_oversized_file(repo, "src/big.ts")
    alpha = (repo / "src" / "big_split" / "alpha.ts").read_text(encoding="utf-8")
    internal = (repo / "src" / "big_split" / "_internal.ts").read_text(
        encoding="utf-8"
    )
    assert "export const alpha = 1;" in alpha
    assert "const helper = 3;" in internal


def test_split_duplicate_export_names_collide(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "dup.ts").write_text(
        "export const foo = 1;\nexport const foo = 2;\n",
        encoding="utf-8",
    )
    changed, _ = _split_oversized_file(tmp_path, "src/dup.ts")
    assert "src/dup_split/foo.ts" in changed
    assert "src/dup_split/foo-2.ts" in changed


# --- DeterministicRemediationExecutor.execute --------------------------------


def test_execute_unapproved_is_dry_run(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, _instruction("oversized_files:over-threshold", "src/big.ts"),
                    approved=False)
    )
    assert result.state == RemediationExecutionState.DRY_RUN
    assert result.changed_files == ()


def test_execute_unapproved_changes_nothing(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, "garbage", approved=False)
    )
    assert result.error is None
    assert "not approved" in result.summary


def test_execute_bad_instruction_fails(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, "please fix this file")
    )
    assert result.state == RemediationExecutionState.FAILED
    assert "Could not parse" in result.error


def test_execute_unsupported_rule_is_dry_run(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, _instruction("secrets:hardcoded", "src/big.ts"))
    )
    assert result.state == RemediationExecutionState.DRY_RUN
    assert "secrets:hardcoded" in result.summary


def test_execute_happy_path(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, _instruction("oversized_files:over-threshold", "src/big.ts"))
    )
    assert result.state == RemediationExecutionState.EXECUTED
    assert "src/big.ts" in result.changed_files


def test_execute_happy_path_result_metadata(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, _instruction("oversized_files:over-threshold", "src/big.ts"))
    )
    assert result.request_id == "req-1"
    assert result.executor_name == "deterministic"
    assert "barrel re-export" in result.summary


def test_execute_missing_file_fails(repo):
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, _instruction("oversized_files:over-threshold", "src/nope.ts"))
    )
    assert result.state == RemediationExecutionState.FAILED
    assert "File not found" in result.error


def _raise_oserror(repo_root, file_path):
    raise OSError("disk full")


def test_execute_os_error_fails(repo, monkeypatch):
    monkeypatch.setattr(det, "_split_oversized_file", _raise_oserror)
    result = DeterministicRemediationExecutor().execute(
        _mk_request(repo, _instruction("oversized_files:over-threshold", "src/big.ts"))
    )
    assert result.state == RemediationExecutionState.FAILED
    assert "disk full" in result.error
