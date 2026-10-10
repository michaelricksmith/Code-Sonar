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
    file_path = str(finding.get("file_path", "your code"))
    if symbol:
        return f"`{symbol}` in {file_path}"
    return file_path


@dataclass(frozen=True, slots=True)
class _ScanSummary:
    """Pre-extracted scan values a deterministic answer is built from."""

    score: Any
    grade: Any
    finding_count: int
    urgent: int
    warning: int
    has_top_findings: bool
    top_label: str
    top_message: str


def _scan_summary(context: dict[str, Any]) -> _ScanSummary:
    det = context.get("deterministic", {}) or {}
    severity = det.get("severity_distribution", {}) or {}
    top = det.get("top_findings", []) or []

    top_label = _finding_label(top[0]) if top else "your top issue"
    top_message = (top[0].get("message") or "") if top else ""
    # Keep it to one sentence so the chat stays scannable.
    if top_message:
        top_message = top_message.split(".")[0].strip() + "."

    return _ScanSummary(
        score=det.get("score", "?"),
        grade=det.get("grade", "?"),
        finding_count=det.get("finding_count", 0),
        urgent=severity.get("critical", 0) + severity.get("error", 0),
        warning=severity.get("warning", 0),
        has_top_findings=bool(top),
        top_label=top_label,
        top_message=top_message,
    )


def _mentions(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)


def _answer_for_question(q: str, summary: _ScanSummary) -> str:
    if _mentions(q, ("next", "start", "do now", "where do i", "what should")):
        return (
            f"Start with your {summary.urgent} urgent issues — they do the most damage "
            f"to your score of {summary.score}. The top one is {summary.top_label}. "
            f"{summary.top_message} "
            f"Tap an issue and hit 'Fix this' for a step-by-step prompt, "
            f"then re-scan to watch the score move."
        )
    if _mentions(q, ("break", "risk", "danger", "safe", "worried")):
        return (
            f"Your score is {summary.score} (grade {summary.grade}) "
            f"with {summary.finding_count} issues. "
            f"The {summary.urgent} urgent ones are the real break-risk — "
            f"starting with {summary.top_label}. "
            f"{summary.top_message} "
            f"Fix the urgent list first and re-scan; each fix moves the score."
        )
    if _mentions(q, ("summar", "overview", "health", "how bad", "status")):
        return (
            f"Code health: score {summary.score} (grade {summary.grade}), "
            f"{summary.finding_count} issues "
            f"— {summary.urgent} urgent, {summary.warning} high. "
            f"Biggest single item: {summary.top_label}. {summary.top_message}"
        )
    if summary.has_top_findings:
        return (
            f"Based on your latest scan (score {summary.score}, grade {summary.grade}): "
            f"the top issue is {summary.top_label}. {summary.top_message} "
            f"Open it and tap 'Fix this' for the step-by-step prompt."
        )
    return (
        f"Your latest scan looks clean — score {summary.score} (grade {summary.grade}). "
        f"Nothing urgent needs your attention right now."
    )


def deterministic_answer(question: str, context: dict[str, Any]) -> GroundedAnswer:
    """Answer from scan data when the LLM provider is unavailable.

    Never raises, never mentions the provider. The user gets a useful,
    grounded answer built from the deterministic scan results, so Ask
    Sonar never feels broken.
    """
    summary = _scan_summary(context)
    q = question.lower().strip()
    return GroundedAnswer(
        answer=_answer_for_question(q, summary),
        used_sources=("deterministic",),
        provider_name="deterministic",
        model_name="scan-data",
    )
