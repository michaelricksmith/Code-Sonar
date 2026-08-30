"""Local Ollama adapter for grounded Ask Sonar answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

from app.ask_sonar.answering import GroundedAnswer

HttpTransport = Callable[[str, bytes, float], bytes]


def _default_transport(url: str, payload: bytes, timeout: float) -> bytes:
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError("Ollama request failed") from exc


@dataclass(slots=True)
class OllamaAnswerProvider:
    """Answer from a sanitized context bundle using a local Ollama model."""

    model_name: str = "llama3.1:8b"
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 45.0
    transport: HttpTransport = _default_transport

    provider_name: str = "ollama"

    def _prompt(self, question: str, context: dict[str, Any]) -> str:
        allowed_sources = list(context.get("allowed_sources", []))
        return (
            "You are Ask Sonar, a grounded assistant for Code Sonar. "
            "Use only the supplied JSON context. Deterministic Code Sonar facts are "
            "authoritative; ML content is advisory only. Never invent repository facts. "
            "Return JSON only with exactly two keys: answer (string) and used_sources "
            "(array of source names). Every used source must come from allowed_sources.\n\n"
            f"Allowed sources: {json.dumps(allowed_sources)}\n"
            f"Question: {question}\n"
            f"Context: {json.dumps(context, sort_keys=True)}"
        )

    def answer(self, question: str, context: dict[str, Any]) -> GroundedAnswer:
        payload = json.dumps(
            {
                "model": self.model_name,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "user",
                        "content": self._prompt(question, context),
                    }
                ],
            }
        ).encode("utf-8")
        raw = self.transport(
            self.base_url.rstrip("/") + "/api/chat",
            payload,
            self.timeout_seconds,
        )

        try:
            outer = json.loads(raw.decode("utf-8"))
            content = outer["message"]["content"]
            parsed = json.loads(content)
            answer = str(parsed["answer"])
            used_sources_raw = parsed["used_sources"]
            if not isinstance(used_sources_raw, list):
                raise TypeError("used_sources must be a list")
            used_sources = tuple(str(source) for source in used_sources_raw)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Ollama returned an invalid grounded-answer payload") from exc

        return GroundedAnswer(
            answer=answer,
            used_sources=used_sources,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
