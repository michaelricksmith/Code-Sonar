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


def _finding_label(finding: dict[str, Any]) -> str:
    symbol = finding.get("symbol")
    file_path = finding.get("file_path", "your code")
    if symbol:
        return f"`{symbol}` in {file_path}"
    return file_path


def deterministic_answer(question: str, context: dict[str, Any]) -> GroundedAnswer:
    """Answer from scan data when the LLM provider is unavailable.

    Never raises, never mentions the provider. The user gets a useful,
    grounded answer built from the deterministic scan results, so Ask
    Sonar never feels broken.
    """
    det = context.get("deterministic", {}) or {}
    score = det.get("score", "?")
    grade = det.get("grade", "?")
    finding_count = det.get("finding_count", 0)
    severity = det.get("severity_distribution", {}) or {}
    top = det.get("top_findings", []) or []

    urgent = severity.get("critical", 0) + severity.get("error", 0)
    top_label = _finding_label(top[0]) if top else "your top issue"
    top_message = (top[0].get("message") or "") if top else ""
    # Keep it to one sentence so the chat stays scannable.
    if top_message:
        top_message = top_message.split(".")[0].strip() + "."

    q = question.lower().strip()

    if any(k in q for k in ("next", "start", "do now", "where do i", "what should")):
        answer = (
            f"Start with your {urgent} urgent issues — they do the most damage "
            f"to your score of {score}. The top one is {top_label}. "
            f"{top_message} "
            f"Tap an issue and hit 'Fix this' for a step-by-step prompt, "
            f"then re-scan to watch the score move."
        )
    elif any(k in q for k in ("break", "risk", "danger", "safe", "worried")):
        answer = (
            f"Your score is {score} (grade {grade}) with {finding_count} issues. "
            f"The {urgent} urgent ones are the real break-risk — "
            f"starting with {top_label}. "
            f"{top_message} "
            f"Fix the urgent list first and re-scan; each fix moves the score."
        )
    elif any(k in q for k in ("summar", "overview", "health", "how bad", "status")):
        answer = (
            f"Code health: score {score} (grade {grade}), {finding_count} issues "
            f"— {urgent} urgent, {severity.get('warning', 0)} high. "
            f"Biggest single item: {top_label}. {top_message}"
        )
    elif top:
        answer = (
            f"Based on your latest scan (score {score}, grade {grade}): "
            f"the top issue is {top_label}. {top_message} "
            f"Open it and tap 'Fix this' for the step-by-step prompt."
        )
    else:
        answer = (
            f"Your latest scan looks clean — score {score} (grade {grade}). "
            f"Nothing urgent needs your attention right now."
        )

    return GroundedAnswer(
        answer=answer,
        used_sources=("deterministic",),
        provider_name="deterministic",
        model_name="scan-data",
    )
