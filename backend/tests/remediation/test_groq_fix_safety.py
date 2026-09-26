"""Groq remediation must never write a broken or cut-off fix to the repo.

Regression guard for the 2026-09-25 production failure: the model returned
a fenced file but max_tokens=4000 cut the response off mid-file, so there
was no closing fence and the run failed with "did not contain a code
block". Worse, a naive tolerant parser would have written half a file.
"""

from __future__ import annotations

import io
import json
import urllib.request

import app.remediation.groq as groq_mod
from app.remediation.contracts import RemediationExecutionState, RemediationRequest


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = io.BytesIO(body)

    def read(self) -> bytes:
        return self._body.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _run_execute(monkeypatch, tmp_path, response_text, original_text):
    target = tmp_path / "target.py"
    target.write_text(original_text, encoding="utf-8")

    body = json.dumps({"choices": [{"message": {"content": response_text}}]}).encode()
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(body)
    )
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    request = RemediationRequest(
        request_id="req-1",
        finding_id="f-1",
        scan_id="s-1",
        repository_path=str(tmp_path),
        instruction="Resolve Code Sonar finding f-1 (PY001) in target.py.",
        approved=True,
    )
    result = groq_mod.GroqRemediationExecutor().execute(request)
    return result, target.read_text(encoding="utf-8")


def test_extract_code_block_unclosed_fence():
    # Truncated response: opening fence, no closing fence.
    out = groq_mod._extract_code_block("```python\nprint('hi')\nprint('cut")
    assert out == "print('hi')\nprint('cut"


def test_extract_code_block_tolerates_crlf_and_trailing_space():
    out = groq_mod._extract_code_block("```python \r\nx = 1\r\n```")
    assert out == "x = 1"


def test_validate_fix_rejects_unparseable_python():
    problem = groq_mod._validate_fix(
        "def broken(:\n    pass", "def broken():\n    pass\n", "a.py"
    )
    assert problem is not None
    assert "does not parse" in problem


def test_validate_fix_rejects_cut_off_file():
    original = "x = 1\n" * 500
    problem = groq_mod._validate_fix("x = 1\n", original, "a.py")
    assert problem is not None
    assert "cut off" in problem


def test_validate_fix_accepts_good_fix():
    original = "x = 1\n"
    assert groq_mod._validate_fix("x = 2\n", original, "a.py") is None


def test_truncated_response_fails_without_touching_file(monkeypatch, tmp_path):
    original = "import os\n\n\ndef f():\n    return 1\n"
    # Well-formed opening, cut off mid-expression, no closing fence.
    truncated = "```python\nimport os\n\n\ndef f():\n    return 1 +"
    result, after = _run_execute(monkeypatch, tmp_path, truncated, original)
    assert result.state == RemediationExecutionState.FAILED
    assert "Nothing was changed" in result.summary
    assert after == original


def test_complete_fix_is_applied(monkeypatch, tmp_path):
    original = "x = 1\n"
    response = "```python\nx = 2\n```"
    result, after = _run_execute(monkeypatch, tmp_path, response, original)
    assert result.state == RemediationExecutionState.EXECUTED
    assert after == "x = 2\n"


def test_max_tokens_scales_with_input(monkeypatch, tmp_path):
    """A large input file must get a large output budget, not fixed 4000."""
    original = "x = 1\n" * 3000  # ~18k chars
    target = tmp_path / "target.py"
    target.write_text(original, encoding="utf-8")

    captured = {}

    def _fake_call_groq(prompt, system=None, max_tokens=4000):
        captured["max_tokens"] = max_tokens
        return "```python\n" + original + "\n```"

    monkeypatch.setattr(groq_mod, "_call_groq", _fake_call_groq)
    request = RemediationRequest(
        request_id="req-1",
        finding_id="f-1",
        scan_id="s-1",
        repository_path=str(tmp_path),
        instruction="Resolve Code Sonar finding f-1 (PY001) in target.py.",
        approved=True,
    )
    groq_mod.GroqRemediationExecutor().execute(request)
    assert captured["max_tokens"] > 4000
