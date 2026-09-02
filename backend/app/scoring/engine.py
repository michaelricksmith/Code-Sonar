"""Deterministic technical-debt scoring for Code Sonar.

The score is authoritative and reproducible. Each finding contributes based on
its analyzer debt points, severity, confidence, category, and repository-path
context. Source/test/fixture context is applied per finding. Non-production
contributions are additionally bounded within each category so intentionally
large test suites and fixtures cannot overwhelm real production findings.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.security.path_classifier import FIXTURE, SOURCE, TEST, classify_path

SCORING_VERSION: str = "1.0"


class ScoringResult:
    def __init__(
        self,
        score: int,
        grade: str,
        total_debt_points: int,
        finding_count: int,
        category_scores: dict[str, int],
        severity_distribution: dict[str, int],
        findings_by_category: dict[str, int],
        findings_source_breakdown: dict[str, int],
    ):
        self.score = score
        self.grade = grade
        self.total_debt_points = total_debt_points
        self.finding_count = finding_count
        self.category_scores = category_scores
        self.severity_distribution = severity_distribution
        self.findings_by_category = findings_by_category
        self.findings_source_breakdown = findings_source_breakdown

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoring_version": SCORING_VERSION,
            "score": self.score,
            "grade": self.grade,
            "total_debt_points": self.total_debt_points,
            "finding_count": self.finding_count,
            "category_scores": self.category_scores,
            "severity_distribution": self.severity_distribution,
            "findings_by_category": self.findings_by_category,
            "findings_source_breakdown": self.findings_source_breakdown,
        }


SEVERITY_WEIGHTS = {
    FindingSeverity.INFO: 1.0,
    FindingSeverity.WARNING: 2.0,
    FindingSeverity.ERROR: 4.0,
    FindingSeverity.CRITICAL: 8.0,
}

SEVERITY_BONUS = {
    FindingSeverity.INFO: 0.0,
    FindingSeverity.WARNING: 1.0,
    FindingSeverity.ERROR: 3.0,
    FindingSeverity.CRITICAL: 8.0,
}

CATEGORY_WEIGHTS = {
    FindingCategory.COMPLEXITY: 0.30,
    FindingCategory.STALENESS: 0.25,
    FindingCategory.SECURITY: 0.25,
    FindingCategory.DUPLICATION: 0.10,
    FindingCategory.TESTING: 0.10,
    FindingCategory.MAINTAINABILITY: 0.10,
}

SOURCE_CONTEXT_MODIFIER: dict[str, float] = {
    SOURCE: 1.0,
    TEST: 0.25,
    FIXTURE: 0.25,
}

LOW_CONFIDENCE_THRESHOLD: float = 0.7
LOW_CONFIDENCE_MODIFIER: float = 0.5

PERFECT_SCORE = 850
MINIMUM_SCORE = 300
MAX_PENALTY = PERFECT_SCORE - MINIMUM_SCORE
NON_SOURCE_CATEGORY_CAP = MAX_PENALTY * SOURCE_CONTEXT_MODIFIER[TEST]


def calculate_score(findings: list[Finding]) -> ScoringResult:
    """Calculate the deterministic Code Sonar score for normalized findings."""
    if not findings:
        return ScoringResult(
            score=PERFECT_SCORE,
            grade="A",
            total_debt_points=0,
            finding_count=0,
            category_scores={cat.value: PERFECT_SCORE for cat in FindingCategory},
            severity_distribution={sev.value: 0 for sev in FindingSeverity},
            findings_by_category={cat.value: 0 for cat in FindingCategory},
            findings_source_breakdown={k: 0 for k in SOURCE_CONTEXT_MODIFIER},
        )

    findings_by_category_map: dict[FindingCategory, list[Finding]] = defaultdict(list)
    for finding in findings:
        findings_by_category_map[finding.category].append(finding)

    total_debt_points = sum(f.debt_points for f in findings)

    severity_counts: dict[str, int] = {sev.value: 0 for sev in FindingSeverity}
    for finding in findings:
        severity_counts[finding.severity.value] += 1

    source_counts: dict[str, int] = {k: 0 for k in SOURCE_CONTEXT_MODIFIER}
    for finding in findings:
        cls = classify_path(finding.file_path)
        source_counts[cls if cls in source_counts else SOURCE] += 1

    category_penalties: dict[FindingCategory, float] = {
        category: _calculate_category_penalty(findings_by_category_map.get(category, []))
        for category in FindingCategory
    }

    total_penalty = sum(
        category_penalties.get(cat, 0.0) * CATEGORY_WEIGHTS.get(cat, 0.0)
        for cat in FindingCategory
    )

    raw_score = PERFECT_SCORE - total_penalty
    final_score = max(MINIMUM_SCORE, min(PERFECT_SCORE, int(raw_score)))

    category_scores = {
        cat.value: max(
            MINIMUM_SCORE,
            min(PERFECT_SCORE, int(PERFECT_SCORE - category_penalties.get(cat, 0.0))),
        )
        for cat in FindingCategory
    }

    findings_count_by_category = {
        cat.value: len(findings_by_category_map.get(cat, [])) for cat in FindingCategory
    }

    return ScoringResult(
        score=final_score,
        grade=_score_to_grade(final_score),
        total_debt_points=total_debt_points,
        finding_count=len(findings),
        category_scores=category_scores,
        severity_distribution=severity_counts,
        findings_by_category=findings_count_by_category,
        findings_source_breakdown=source_counts,
    )


def _confidence_modifier(finding: Finding) -> float:
    if finding.confidence < LOW_CONFIDENCE_THRESHOLD:
        return LOW_CONFIDENCE_MODIFIER
    return 1.0


def _calculate_category_penalty(findings: list[Finding]) -> float:
    """Calculate a bounded category penalty with per-finding context weighting.

    Production and non-production contributions are accumulated separately.
    Test/fixture findings still receive their 0.25 per-finding modifier, and
    their aggregate contribution is capped at 25% of the category's available
    penalty. This prevents intentionally repetitive fixtures from dominating a
    repository's score while leaving their raw findings and debt visible.
    """
    if not findings:
        return 0.0

    source_penalty = 0.0
    non_source_penalty = 0.0
    for finding in findings:
        severity_weight = SEVERITY_WEIGHTS.get(finding.severity, 1.0)
        confidence_modifier = _confidence_modifier(finding)
        path_class = classify_path(finding.file_path)
        context_modifier = SOURCE_CONTEXT_MODIFIER.get(path_class, 1.0)
        contribution = (
            finding.debt_points * severity_weight * confidence_modifier
            + SEVERITY_BONUS.get(finding.severity, 0.0)
        ) * context_modifier
        if path_class == SOURCE:
            source_penalty += contribution
        else:
            non_source_penalty += contribution

    bounded_non_source = min(NON_SOURCE_CATEGORY_CAP, non_source_penalty)
    return min(MAX_PENALTY, source_penalty + bounded_non_source)


def _score_to_grade(score: int) -> str:
    if score >= 800:
        return "A"
    if score >= 740:
        return "B"
    if score >= 670:
        return "C"
    if score >= 580:
        return "D"
    return "F"
