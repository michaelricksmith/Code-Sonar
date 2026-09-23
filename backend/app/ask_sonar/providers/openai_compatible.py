"""OpenAI-compatible hosted adapter for grounded Ask Sonar answers.

Works against https://api.openai.com/v1 by default; any OpenAI-compatible
endpoint (self-hosted gateways, other vendors) can be used via base_url.
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

# (url, payload, timeout_seconds, headers) -> raw response body
HttpTransport = Callable[[str, bytes, float, Mapping[str, str]], bytes]

SYSTEM_INSTRUCTION = (
    "You are Ask Sonar, a grounded assistant for Code Sonar. Explain everything "
    "in plain language for a non-technical user — avoid jargon and do not show "
    "code unless the user asks for it. Use only the supplied JSON context. "
    "Deterministic Code Sonar facts are authoritative; ML content is advisory "
    "only. Never invent repository facts. Return JSON only with exactly two "
    "keys: answer (string) and used_sources (array of source names). Every "
    "used source must come from allowed_sources."
)


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
        raise RuntimeError("OpenAI-compatible request failed") from exc


@dataclass(slots=True)
class OpenAICompatibleProvider:
    """Answer from a sanitized context bundle using an OpenAI-compatible API."""

    api_key: str
    model_name: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0
    transport: HttpTransport = _default_transport

    provider_name: str = "openai"

    def _prompt(self, question: str, context: dict[str, Any]) -> str:
        allowed_sources = list(context.get("allowed_sources", []))
        return (
            f"Allowed sources: {json.dumps(allowed_sources)}\n"
            f"Question: {question}\n"
            f"Context: {json.dumps(context, sort_keys=True)}"
        )

    def answer(self, question: str, context: dict[str, Any]) -> GroundedAnswer:
        payload = json.dumps(
            {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": self._prompt(question, context)},
                ],
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        raw = self.transport(
            self.base_url.rstrip("/") + "/chat/completions",
            payload,
            self.timeout_seconds,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            outer = json.loads(raw.decode("utf-8"))
            content = outer["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            answer = str(parsed["answer"])
            used_sources_raw = parsed["used_sources"]
            if not isinstance(used_sources_raw, list):
                raise TypeError("used_sources must be a list")
            used_sources = tuple(str(source) for source in used_sources_raw)
        except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
            raise ValueError(
                "OpenAI-compatible provider returned an invalid grounded-answer payload"
            ) from exc

        return GroundedAnswer(
            answer=answer,
            used_sources=used_sources,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
