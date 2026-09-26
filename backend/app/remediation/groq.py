"""Groq-powered remediation executor — AI fixes via API, no binary needed.

Uses Groq's OpenAI-compatible API to generate code fixes for findings
that the deterministic executor cannot handle (logic bugs, complex
refactors, etc.).

Requires:
- GROQ_API_KEY (or OPENAI_API_KEY) environment variable
- CODE_SONAR_GROQ_MODEL (optional, defaults to openai/gpt-oss-120b)

The executor:
1. Reads the target file
2. Sends the finding + code to Groq with a fix prompt
3. Parses the returned full file content from a markdown code block
4. Validates it (must parse; must not be a cut-off fragment) and applies
   the change to the worktree — nothing is written unless it validates
5. Returns the changed files

If the API call fails, returns FAILED with the error (no fake success).
"""

from __future__ import annotations

import ast
import json
import os
import re
import urllib.request
from pathlib import Path

from app.remediation.contracts import (
    RemediationExecutionResult,
    RemediationExecutionState,
    RemediationRequest,
)
from app.remediation.deterministic import (
    SUPPORTED_RULES as DETERMINISTIC_RULES,
)
from app.remediation.deterministic import (
    DeterministicRemediationExecutor,
    _parse_instruction,
)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# llama-3.3-70b-versatile was decommissioned by Groq on 2026-08-16;
# openai/gpt-oss-120b is Groq's recommended replacement.
DEFAULT_MODEL = "openai/gpt-oss-120b"

# Maximum file size to send to the API (characters). Larger files are
# truncated with a notice to avoid excessive token usage.
MAX_FILE_CHARS = 20000


def _get_api_key() -> str:
    """Get Groq API key from environment."""
    return (
        os.getenv("GROQ_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )


def _get_model() -> str:
    """Get the Groq model to use."""
    return os.getenv("CODE_SONAR_GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _call_groq(prompt: str, system: str | None = None, max_tokens: int = 4000) -> str:
    """Call Groq chat completions API. Raises on failure."""
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY (or OPENAI_API_KEY) is not set; "
            "cannot use Groq remediation executor"
        )

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": _get_model(),
        "messages": messages,
        "temperature": 0.1,  # Low temp for deterministic fixes
        "max_tokens": max_tokens,
    }
    # gpt-oss is a reasoning model: it spends part of the token budget on
    # hidden reasoning, which can starve the actual answer at low budgets.
    # Keep reasoning cheap so the budget goes to the fixed file.
    if "gpt-oss" in _get_model():
        payload["reasoning_effort"] = "low"

    req = urllib.request.Request(
        GROQ_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # Groq sits behind Cloudflare, which 403s (error code 1010)
            # requests carrying urllib's default User-Agent before auth
            # is even checked. Identify the client explicitly.
            "User-Agent": "Code-Sonar/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Groq API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Groq API connection failed: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Groq API response format: {exc}") from exc
    if not isinstance(content, str):
        raise RuntimeError(f"Unexpected Groq API response format: {type(content).__name__}")
    return content


def _extract_code_block(response: str) -> str | None:
    """Extract the first fenced code block from a model response.

    Tolerates a missing closing fence (the response was cut off): returns
    everything after the opening fence so the caller can validate it.
    Validation must reject incomplete output — never write it blindly.
    """
    # Match ```language\n...code...\n``` (tolerant of trailing spaces/CR).
    m = re.search(r"```[ \t]*(?:\w+)?[ \t]*\r?\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: opening fence with no closing fence — truncated response.
    m = re.search(r"```[ \t]*(?:\w+)?[ \t]*\r?\n(.*)$", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _validate_fix(fixed: str, original: str, file_path: str) -> str | None:
    """Return an error message if the fix must NOT be applied, else None.

    This is the last line of defense before overwriting a user's file:
    reject empty output, code that does not parse, and output that is far
    shorter than the original (a cut-off response masquerading as a fix).
    """
    if not fixed.strip():
        return "Groq returned an empty fix"
    if file_path.endswith(".py"):
        try:
            ast.parse(fixed)
        except SyntaxError as exc:
            return f"Groq returned code that does not parse ({exc}); not applied"
    # A full-file rewrite should be roughly the original size. Much shorter
    # means the response was cut off mid-file.
    if len(fixed) < 0.5 * len(original):
        return (
            "Groq's response was cut off before the complete file "
            f"({len(fixed)} chars vs {len(original)} in the original); not applied"
        )
    return None


def _truncate_for_prompt(original: str) -> tuple[str, bool]:
    """Truncate very large files to control token usage; return (code, truncated)."""
    truncated = len(original) > MAX_FILE_CHARS
    code_for_prompt = original[:MAX_FILE_CHARS]
    if truncated:
        code_for_prompt += "\n\n# ... (file truncated for length) ..."
    return code_for_prompt, truncated


def _build_fix_prompt(
    request: RemediationRequest, rule_id: str, file_path: str, code_for_prompt: str
) -> tuple[str, str, int]:
    """Build the (prompt, system, max_tokens) triple for the Groq fix request."""
    system = (
        "You are a precise code-fix assistant. Given a code finding "
        "and the file content, output ONLY the corrected full file "
        "content in a markdown code block. Do not explain. Do not "
        "add comments about the fix. Preserve all behavior except "
        "what the finding requires. Make the smallest safe change."
    )
    prompt = (
        f"Fix this Code Sonar finding:\n\n"
        f"Rule: {rule_id}\n"
        f"File: {file_path}\n"
        f"Finding: {request.instruction}\n\n"
        f"Current file content:\n```\n{code_for_prompt}\n```\n\n"
        f"Output the complete corrected file in a code block."
    )

    # The model must return the WHOLE file: size the token budget from the
    # input (~1 token per 3 chars of code, plus headroom). A fixed 4000
    # budget cannot hold a large file, so the response gets cut off and
    # there is no usable fix to extract.
    needed_tokens = int(len(code_for_prompt) / 3 * 1.3) + 500
    max_tokens = min(max(4000, needed_tokens), 16000)
    return prompt, system, max_tokens


class GroqRemediationExecutor:
    """AI-powered remediation via Groq API.

    Falls back to deterministic executor for structural rules
    (oversized files) to save API quota. Uses Groq for everything else.
    """

    executor_name = "groq"

    def __init__(self) -> None:
        self._deterministic = DeterministicRemediationExecutor()

    def _failed(
        self, request: RemediationRequest, error: str, summary: str
    ) -> RemediationExecutionResult:
        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=RemediationExecutionState.FAILED,
            error=error,
            summary=summary,
        )

    def _dry_run(
        self, request: RemediationRequest, summary: str
    ) -> RemediationExecutionResult:
        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=RemediationExecutionState.DRY_RUN,
            summary=summary,
        )

    def _deterministic_result(
        self, request: RemediationRequest
    ) -> RemediationExecutionResult:
        result = self._deterministic.execute(request)
        # Re-label the executor so the UI shows the right source.
        return RemediationExecutionResult(
            request_id=result.request_id,
            executor_name=self.executor_name,
            state=result.state,
            changed_files=result.changed_files,
            summary=f"[deterministic] {result.summary}",
            build_passed=result.build_passed,
            tests_passed=result.tests_passed,
            error=result.error,
        )

    def _apply_fix(
        self,
        request: RemediationRequest,
        rule_id: str,
        file_path: str,
        full: Path,
        fixed: str,
        original: str,
        truncated: bool,
    ) -> RemediationExecutionResult:
        if fixed.strip() == original.strip():
            return self._dry_run(
                request,
                "Groq returned the file unchanged; "
                "no fix was necessary or possible.",
            )

        try:
            full.write_text(fixed + "\n", encoding="utf-8")
        except OSError as exc:
            return self._failed(
                request, str(exc), f"Failed to write fixed file: {exc}"
            )

        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=RemediationExecutionState.EXECUTED,
            changed_files=(file_path,),
            summary=(
                f"Groq ({_get_model()}) generated a fix for {rule_id} "
                f"in {file_path}."
                + (" (input was truncated)" if truncated else "")
            ),
        )

    def _remediate_with_groq(
        self, request: RemediationRequest, rule_id: str, file_path: str
    ) -> RemediationExecutionResult:
        # Use Groq API for everything else.
        repo_root = Path(request.repository_path)
        full = repo_root / file_path
        if not full.is_file():
            return self._failed(request, f"File not found: {file_path}",
                                f"Groq executor could not find {file_path}.")

        try:
            original = full.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return self._failed(request, str(exc),
                                f"Groq executor could not read {file_path}: {exc}")

        code_for_prompt, truncated = _truncate_for_prompt(original)
        prompt, system, max_tokens = _build_fix_prompt(
            request, rule_id, file_path, code_for_prompt
        )

        try:
            response = _call_groq(prompt, system=system, max_tokens=max_tokens)
        except RuntimeError as exc:
            return self._failed(request, str(exc), f"Groq API call failed: {exc}")

        fixed = _extract_code_block(response)
        if not fixed:
            return self._failed(request, "Groq response did not contain a code block",
                                "Groq did not return a usable fix. "
                                f"Raw response preview: {response[:200]}...")

        # Never overwrite the user's file with a broken or cut-off fix.
        problem = _validate_fix(fixed, original, file_path)
        if problem:
            return self._failed(request, problem,
                                f"Groq did not return a usable fix. {problem}. "
                                "Nothing was changed.")

        return self._apply_fix(request, rule_id, file_path, full, fixed, original, truncated)

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult:
        if not request.approved:
            return self._dry_run(
                request,
                "Remediation request is not approved; no changes were attempted.",
            )

        parsed = _parse_instruction(request.instruction)
        if parsed is None:
            return self._failed(
                request,
                "Could not parse rule_id and file_path from instruction",
                "Groq executor could not understand the request.",
            )

        rule_id, file_path = parsed

        # Use deterministic for structural rules (free, no API quota).
        if rule_id in DETERMINISTIC_RULES:
            return self._deterministic_result(request)

        return self._remediate_with_groq(request, rule_id, file_path)
