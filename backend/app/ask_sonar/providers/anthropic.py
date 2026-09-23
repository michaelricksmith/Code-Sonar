"""Anthropic native Messages API adapter for grounded Ask Sonar answers.

Follows the OllamaAnswerProvider dataclass pattern with an injectable
transport. BYOK API keys are transient per-request values: they are passed in
memory for the single call and are never persisted or logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast
from urllib import error, request

from app.ask_sonar.answering import GroundedAnswer
from app.ask_sonar.providers.openai_compatible import SYSTEM_INSTRUCTION

# (url, payload, timeout_seconds, headers) -> raw response body
HttpTransport = Callable[[str, bytes, float, Mapping[str, str]], bytes]

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


def _default_transport(
    url: str, payload: bytes, timeout: float, headers: Mapping[str, str]
) -> bytes:
    req = request.Request(
        url,
        data=payload,
        headers=dict(headers),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return cast(bytes, response.read())
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError("Anthropic request failed") from exc


@dataclass(slots=True)
class AnthropicProvider:
    """Answer from a sanitized context bundle using the Anthropic Messages API."""

    api_key: str
    model_name: str = "claude-haiku-4-5"
    timeout_seconds: float = 45.0
    transport: HttpTransport = _default_transport

    provider_name: str = "anthropic"

    def _prompt(self, question: str, context: dict[str, Any]) -> str:
        allowed_sources = list(context.get("allowed_sources", []))
        return (
            f"Allowed sources: {json.dumps(allowed_sources)}\n"
            f"Question: {question}\n"
            f"Context: {json.dumps(context, sort_keys=True)}\n\n"
            "Reply with JSON only: {\"answer\": string, \"used_sources\": string[]}."
        )

    def answer(self, question: str, context: dict[str, Any]) -> GroundedAnswer:
        payload = json.dumps(
            {
                "model": self.model_name,
                "max_tokens": 1024,
                "system": SYSTEM_INSTRUCTION,
                "messages": [
                    {"role": "user", "content": self._prompt(question, context)}
                ],
            }
        ).encode("utf-8")
        raw = self.transport(
            _ANTHROPIC_MESSAGES_URL,
            payload,
            self.timeout_seconds,
            {
                "x-api-key": self.api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
        )

        try:
            outer = json.loads(raw.decode("utf-8"))
            content = outer["content"][0]["text"]
            parsed = json.loads(content)
            answer = str(parsed["answer"])
            used_sources_raw = parsed["used_sources"]
            if not isinstance(used_sources_raw, list):
                raise TypeError("used_sources must be a list")
            used_sources = tuple(str(source) for source in used_sources_raw)
        except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Anthropic returned an invalid grounded-answer payload"
            ) from exc

        return GroundedAnswer(
            answer=answer,
            used_sources=used_sources,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
