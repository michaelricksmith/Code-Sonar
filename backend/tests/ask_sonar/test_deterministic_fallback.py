"""Tests for the Ask Sonar deterministic fallback.

When the LLM provider is missing or fails, Ask Sonar must answer from the
deterministic scan data instead of surfacing a raw provider error. The user
should never see "couldn't answer".
"""

from __future__ import annotations

from app.ask_sonar.answering import deterministic_answer


def _context() -> dict:
    return {
        "deterministic": {
            "score": 527,
            "grade": "F",
            "finding_count": 284,
            "severity_distribution": {
                "critical": 3,
                "error": 10,
                "warning": 74,
                "info": 50,
            },
            "top_findings": [
                {
                    "symbol": "validate_artifact",
                    "file_path": "backend/app/calibration/validation.py",
                    "message": "Cyclomatic complexity 41 exceeds limit 10.",
                }
            ],
        },
        "allowed_sources": ["deterministic"],
    }


def test_fallback_next_steps_mentions_urgent_and_score():
    result = deterministic_answer("what should I do next?", _context())
    assert "527" in result.answer
    assert "13 urgent" in result.answer
    assert "validate_artifact" in result.answer
    assert result.provider_name == "deterministic"
    assert result.used_sources == ("deterministic",)


def test_fallback_break_risk_mentions_grade():
    result = deterministic_answer("Will this break my app?", _context())
    assert "grade F" in result.answer
    assert "284 issues" in result.answer


def test_fallback_never_empty_and_never_mentions_provider():
    for question in ["hello", "", "explain quantum tunneling in my codebase"]:
        result = deterministic_answer(question, _context())
        assert result.answer.strip()
        lowered = result.answer.lower()
        assert "unauthorized" not in lowered
        assert "couldn't answer" not in lowered
        assert "provider" not in lowered


def test_fallback_empty_scan_is_reassuring():
    ctx = _context()
    ctx["deterministic"]["finding_count"] = 0
    ctx["deterministic"]["top_findings"] = []
    ctx["deterministic"]["score"] = 850
    ctx["deterministic"]["grade"] = "A"
    result = deterministic_answer("what should I do next?", ctx)
    assert "clean" in result.answer.lower()
