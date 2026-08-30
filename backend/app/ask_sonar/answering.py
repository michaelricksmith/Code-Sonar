"""Provider-neutral answer contract for Ask Sonar.

Providers receive only the pre-built grounding context. They do not receive a
repository path, filesystem handle, scanner service, or permission to rescan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """One provider response with explicit source declarations."""

    answer: str
    used_sources: tuple[str, ...]
    provider_name: str
    model_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "used_sources": list(self.used_sources),
            "provider_name": self.provider_name,
            "model_name": self.model_name,
        }


class AnswerProviderProtocol(Protocol):
    """A text-generation provider constrained to supplied grounding context."""

    provider_name: str
    model_name: str

    def answer(self, question: str, context: dict[str, Any]) -> GroundedAnswer: ...


def validate_grounded_answer(
    result: GroundedAnswer,
    context: dict[str, Any],
) -> GroundedAnswer:
    """Reject provider-declared sources that are not present in the context."""
    allowed = set(context.get("allowed_sources", []))
    unknown = sorted(set(result.used_sources) - allowed)
    if unknown:
        raise ValueError("Provider cited unavailable sources: " + ", ".join(unknown))
    if not result.answer.strip():
        raise ValueError("Provider returned an empty answer")
    return result
