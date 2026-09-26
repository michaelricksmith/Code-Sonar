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
3. Parses the returned unified diff or full file content
4. Applies the change to the worktree
5. Returns the changed files

If the API call fails, returns FAILED with the error (no fake success).
"""

from __future__ import annotations

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


def _call_groq(prompt: str, system: str | None = None) -> str:
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
        "max_tokens": 4000,
    }

    req = urllib.request.Request(
        GROQ_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
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
    """Extract the first code block from a markdown response."""
    # Match ```language\n...code...\n``` or ```\n...code...\n```
    m = re.search(r"```(?:\w+)?\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


class GroqRemediationExecutor:
    """AI-powered remediation via Groq API.

    Falls back to deterministic executor for structural rules
    (oversized files) to save API quota. Uses Groq for everything else.
    """

    executor_name = "groq"

    def __init__(self) -> None:
        self._deterministic = DeterministicRemediationExecutor()

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult:
        if not request.approved:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.DRY_RUN,
                summary="Remediation request is not approved; no changes were attempted.",
            )

        parsed = _parse_instruction(request.instruction)
        if parsed is None:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error="Could not parse rule_id and file_path from instruction",
                summary="Groq executor could not understand the request.",
            )

        rule_id, file_path = parsed

        # Use deterministic for structural rules (free, no API quota).
        if rule_id in DETERMINISTIC_RULES:
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

        # Use Groq API for everything else.
        repo_root = Path(request.repository_path)
        full = repo_root / file_path
        if not full.is_file():
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error=f"File not found: {file_path}",
                summary=f"Groq executor could not find {file_path}.",
            )

        try:
            original = full.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error=str(exc),
                summary=f"Groq executor could not read {file_path}: {exc}",
            )

        # Truncate very large files to control token usage.
        truncated = len(original) > MAX_FILE_CHARS
        code_for_prompt = original[:MAX_FILE_CHARS]
        if truncated:
            code_for_prompt += "\n\n# ... (file truncated for length) ..."

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

        try:
            response = _call_groq(prompt, system=system)
        except RuntimeError as exc:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error=str(exc),
                summary=f"Groq API call failed: {exc}",
            )

        fixed = _extract_code_block(response)
        if not fixed:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error="Groq response did not contain a code block",
                summary=(
                    "Groq did not return a usable fix. "
                    f"Raw response preview: {response[:200]}..."
                ),
            )

        if fixed.strip() == original.strip():
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.DRY_RUN,
                summary=(
                    "Groq returned the file unchanged; "
                    "no fix was necessary or possible."
                ),
            )

        try:
            full.write_text(fixed + "\n", encoding="utf-8")
        except OSError as exc:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error=str(exc),
                summary=f"Failed to write fixed file: {exc}",
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
