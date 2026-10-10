"""Unit tests for ``app.remediation.groq``.

``test_groq_fix_safety.py`` covers the safety-critical path of the Groq
remediation executor: code-block extraction of truncated responses,
``_validate_fix`` rejection of broken/cut-off fixes, the end-to-end guard
that a truncated model response never touches the repo, the happy path of
applying a complete fix, and token-budget scaling. ``test_groq_user_agent.py``
covers the Cloudflare User-Agent regression guard.

This module covers the rest of the executor's public surface:
``_get_api_key``/``_get_model`` env handling, ``_call_groq`` error paths
(missing key, HTTP errors, connection failures, malformed responses) and
payload shape (system message, ``reasoning_effort`` for gpt-oss models),
``_truncate_for_prompt`` boundaries, ``_build_fix_prompt`` contents and
token budget, and ``execute`` dispatch: dry-run for unapproved requests,
unparseable instructions, deterministic fallback for structural rules,
missing files, API failures, unusable model output, unchanged-file dry-run,
and the truncated-input summary note.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

import app.remediation.groq as groq_mod
from app.remediation.contracts import RemediationExecutionState, RemediationRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeHTTPResponse(io.BytesIO):
    """Minimal urllib response: BytesIO already speaks the context-manager
    protocol (``__enter__``/``__exit__``) that ``_call_groq`` relies on."""


def _mk_request(
    tmp_path,
    rule_id: str = "PY001",
    file_name: str = "target.py",
    approved: bool = True,
    instruction: str | None = None,
) -> RemediationRequest:
    if instruction is None:
        instruction = (
            f"Resolve Code Sonar finding f-1 ({rule_id}) in {file_name}."
        )
    return RemediationRequest(
        request_id="req-1",
        finding_id="f-1",
        scan_id="s-1",
        repository_path=str(tmp_path),
        instruction=instruction,
        approved=approved,
    )


def _chat_body(content) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode("utf-8")


def _install_urlopen(monkeypatch, body: bytes, captured: dict) -> None:
    def _fake(req, timeout=None):
        captured["request"] = req
        return _FakeHTTPResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")


def _request_payload(captured: dict) -> dict:
    return json.loads(captured["request"].data.decode("utf-8"))


# ---------------------------------------------------------------------------
# Env config: _get_api_key / _get_model
# ---------------------------------------------------------------------------


class TestApiKey:
    def test_groq_key_wins_over_openai_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", " groq-key ")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        assert groq_mod._get_api_key() == "groq-key"

    def test_falls_back_to_openai_key(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        assert groq_mod._get_api_key() == "openai-key"

    def test_empty_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert groq_mod._get_api_key() == ""


class TestModel:
    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("CODE_SONAR_GROQ_MODEL", raising=False)
        assert groq_mod._get_model() == groq_mod.DEFAULT_MODEL

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CODE_SONAR_GROQ_MODEL", "llama-custom")
        assert groq_mod._get_model() == "llama-custom"

    def test_blank_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CODE_SONAR_GROQ_MODEL", "   ")
        assert groq_mod._get_model() == groq_mod.DEFAULT_MODEL


# ---------------------------------------------------------------------------
# _call_groq: payload, headers, errors
# ---------------------------------------------------------------------------


class TestCallGroq:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError) as excinfo:
            groq_mod._call_groq("hello")
        assert "GROQ_API_KEY" in str(excinfo.value)

    def test_success_returns_content(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body("```python\nx = 1\n```"), captured)
        assert groq_mod._call_groq("hello") == "```python\nx = 1\n```"

    def test_system_message_included(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body("ok"), captured)
        groq_mod._call_groq("hello", system="be terse")
        roles = [m["role"] for m in _request_payload(captured)["messages"]]
        assert roles == ["system", "user"]

    def test_no_system_message_by_default(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body("ok"), captured)
        groq_mod._call_groq("hello")
        roles = [m["role"] for m in _request_payload(captured)["messages"]]
        assert roles == ["user"]

    def test_reasoning_effort_for_gpt_oss(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body("ok"), captured)
        monkeypatch.setenv("CODE_SONAR_GROQ_MODEL", "openai/gpt-oss-120b")
        groq_mod._call_groq("hello")
        assert _request_payload(captured)["reasoning_effort"] == "low"

    def test_no_reasoning_effort_for_other_models(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body("ok"), captured)
        monkeypatch.setenv("CODE_SONAR_GROQ_MODEL", "llama-3.3-70b")
        groq_mod._call_groq("hello")
        assert "reasoning_effort" not in _request_payload(captured)

    def test_bearer_auth_header_sent(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body("ok"), captured)
        groq_mod._call_groq("hello")
        assert captured["request"].get_header("Authorization") == "Bearer test-key"

    def test_http_error_raises_with_status(self, monkeypatch):
        err = urllib.error.HTTPError(
            groq_mod.GROQ_API_URL,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error": "bad key"}'),
        )

        def _fake(req, timeout=None):
            raise err

        monkeypatch.setattr(urllib.request, "urlopen", _fake)
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        with pytest.raises(RuntimeError) as excinfo:
            groq_mod._call_groq("hello")
        assert "HTTP 401" in str(excinfo.value)

    def test_connection_failure_raises(self, monkeypatch):
        def _fake(req, timeout=None):
            raise urllib.error.URLError("dns boom")

        monkeypatch.setattr(urllib.request, "urlopen", _fake)
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        with pytest.raises(RuntimeError) as excinfo:
            groq_mod._call_groq("hello")
        assert "connection failed" in str(excinfo.value)

    def test_malformed_response_raises(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, b'{"nope": true}', captured)
        with pytest.raises(RuntimeError) as excinfo:
            groq_mod._call_groq("hello")
        assert "Unexpected Groq API response format" in str(excinfo.value)

    def test_non_string_content_raises(self, monkeypatch):
        captured: dict = {}
        _install_urlopen(monkeypatch, _chat_body(12345), captured)
        with pytest.raises(RuntimeError) as excinfo:
            groq_mod._call_groq("hello")
        assert "Unexpected Groq API response format" in str(excinfo.value)


# ---------------------------------------------------------------------------
# _extract_code_block / _validate_fix extras (beyond test_groq_fix_safety.py)
# ---------------------------------------------------------------------------


class TestExtractCodeBlockExtras:
    def test_no_fence_returns_none(self):
        assert groq_mod._extract_code_block("just some prose") is None

    def test_empty_fence_returns_empty_string(self):
        assert groq_mod._extract_code_block("```python\n\n```") == ""


class TestValidateFixExtras:
    def test_empty_fix_rejected(self):
        problem = groq_mod._validate_fix("   \n  ", "x = 1\n", "a.py")
        assert problem is not None
        assert "empty fix" in problem

    def test_non_python_skips_syntax_check(self):
        fixed = "def broken(:" * 50  # invalid Python, plenty long
        problem = groq_mod._validate_fix(fixed, fixed, "notes.txt")
        assert problem is None


# ---------------------------------------------------------------------------
# _truncate_for_prompt
# ---------------------------------------------------------------------------


class TestTruncateForPrompt:
    def test_small_file_untouched(self):
        code = "x = 1\n"
        out, truncated = groq_mod._truncate_for_prompt(code)
        assert out == code
        assert truncated is False

    def test_boundary_size_not_truncated(self):
        code = "x" * groq_mod.MAX_FILE_CHARS
        out, truncated = groq_mod._truncate_for_prompt(code)
        assert out == code
        assert truncated is False

    def test_large_file_truncated_with_notice(self):
        code = "x" * (groq_mod.MAX_FILE_CHARS + 10)
        out, truncated = groq_mod._truncate_for_prompt(code)
        assert truncated is True
        assert out.startswith("x" * groq_mod.MAX_FILE_CHARS)
        assert "truncated for length" in out


# ---------------------------------------------------------------------------
# _build_fix_prompt
# ---------------------------------------------------------------------------


class TestBuildFixPrompt:
    def test_prompt_contains_finding_details(self, tmp_path):
        request = _mk_request(tmp_path)
        prompt, system, max_tokens = groq_mod._build_fix_prompt(
            request, "PY001", "target.py", "x = 1\n"
        )
        assert "PY001" in prompt
        assert "target.py" in prompt
        assert request.instruction in prompt
        assert "x = 1" in prompt
        assert len(system) > 0
        assert max_tokens >= 4000

    def test_huge_input_caps_budget(self, tmp_path):
        request = _mk_request(tmp_path)
        code = "x = 1\n" * 20000  # ~120k chars, way past the cap
        _, _, max_tokens = groq_mod._build_fix_prompt(
            request, "PY001", "target.py", code
        )
        assert max_tokens == 16000


# ---------------------------------------------------------------------------
# execute: dispatch paths
# ---------------------------------------------------------------------------


class TestExecuteDispatch:
    def test_unapproved_request_is_dry_run(self, tmp_path):
        request = _mk_request(tmp_path, approved=False)
        result = groq_mod.GroqRemediationExecutor().execute(request)
        assert result.state == RemediationExecutionState.DRY_RUN
        assert result.executor_name == "groq"
        assert result.changed_files == ()

    def test_unparseable_instruction_fails(self, tmp_path):
        request = _mk_request(tmp_path, instruction="do something vague")
        result = groq_mod.GroqRemediationExecutor().execute(request)
        assert result.state == RemediationExecutionState.FAILED
        assert "parse" in result.error

    def test_deterministic_rule_delegates_and_relabels(self, tmp_path):
        (tmp_path / "big.py").write_text("x = 1\n", encoding="utf-8")
        request = _mk_request(tmp_path, rule_id="oversized_files:over-threshold")
        result = groq_mod.GroqRemediationExecutor().execute(request)
        assert result.executor_name == "groq"
        assert result.summary.startswith("[deterministic]")

    def test_missing_file_fails(self, tmp_path):
        request = _mk_request(tmp_path, file_name="nope.py")
        result = groq_mod.GroqRemediationExecutor().execute(request)
        assert result.state == RemediationExecutionState.FAILED
        assert "File not found" in result.error

    def test_api_failure_fails_with_error(self, tmp_path, monkeypatch):
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")

        def _boom(prompt, system=None, max_tokens=4000):
            raise RuntimeError("Groq API HTTP 500: boom")

        monkeypatch.setattr(groq_mod, "_call_groq", _boom)
        result = groq_mod.GroqRemediationExecutor().execute(
            _mk_request(tmp_path)
        )
        assert result.state == RemediationExecutionState.FAILED
        assert "Groq API call failed" in result.summary
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == "x = 1\n"

    def test_response_without_code_block_fails(self, tmp_path, monkeypatch):
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(
            groq_mod, "_call_groq", lambda *a, **k: "no code here, sorry"
        )
        result = groq_mod.GroqRemediationExecutor().execute(
            _mk_request(tmp_path)
        )
        assert result.state == RemediationExecutionState.FAILED
        assert "did not contain a code block" in result.error

    def test_broken_python_rejected_file_untouched(self, tmp_path, monkeypatch):
        original = "x = 1\n"
        (tmp_path / "target.py").write_text(original, encoding="utf-8")
        monkeypatch.setattr(
            groq_mod,
            "_call_groq",
            lambda *a, **k: "```python\n" + "def broken(:\n" * 200 + "\n```",
        )
        result = groq_mod.GroqRemediationExecutor().execute(
            _mk_request(tmp_path)
        )
        assert result.state == RemediationExecutionState.FAILED
        assert "Nothing was changed" in result.summary
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == original

    def test_unchanged_fix_is_dry_run(self, tmp_path, monkeypatch):
        original = "x = 1\n"
        (tmp_path / "target.py").write_text(original, encoding="utf-8")
        monkeypatch.setattr(
            groq_mod, "_call_groq", lambda *a, **k: "```python\nx = 1\n```"
        )
        result = groq_mod.GroqRemediationExecutor().execute(
            _mk_request(tmp_path)
        )
        assert result.state == RemediationExecutionState.DRY_RUN
        assert result.changed_files == ()
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == original

    def test_success_writes_fix(self, tmp_path, monkeypatch):
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(
            groq_mod, "_call_groq", lambda *a, **k: "```python\nx = 2\n```"
        )
        result = groq_mod.GroqRemediationExecutor().execute(
            _mk_request(tmp_path)
        )
        assert result.state == RemediationExecutionState.EXECUTED
        assert result.changed_files == ("target.py",)
        assert result.executor_name == "groq"
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == "x = 2\n"

    def test_truncated_input_noted_in_summary(self, tmp_path, monkeypatch):
        original = "x = 1\n" * 4100  # over MAX_FILE_CHARS (20000)
        (tmp_path / "target.py").write_text(original, encoding="utf-8")
        fixed = "x = 2\n" + "x = 1\n" * 4099
        monkeypatch.setattr(
            groq_mod, "_call_groq", lambda *a, **k: f"```python\n{fixed}\n```"
        )
        result = groq_mod.GroqRemediationExecutor().execute(
            _mk_request(tmp_path)
        )
        assert result.state == RemediationExecutionState.EXECUTED
        assert "(input was truncated)" in result.summary
