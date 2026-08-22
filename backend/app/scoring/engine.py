"""Deterministic scoring engine for Code Sonar.

Calculates technical debt scores from normalized findings.
Score range: 300-850 (FICO-like scale)
"""

from collections import defaultdict
from typing import Any

from app.models.finding import Finding, FindingCategory, FindingSeverity


class ScoringResult:
    """Scoring engine output."""

    def __init__(
        self,
        score: int,
        grade: str,
        total_debt_points: int,
        finding_count: int,
        category_scores: dict[str, int],
        severity_distribution: dict[str, int],
        findings_by_category: dict[str, int],
    ):
        self.score = score
        self.grade = grade
        self.total_debt_points = total_debt_points
        self.finding_count = finding_count
        self.category_scores = category_scores
        self.severity_distribution = severity_distribution
        self.findings_by_category = findings_by_category

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API serialization."""
        return {
            "score": self.score,
            "grade": self.grade,
            "total_debt_points": self.total_debt_points,
            "finding_count": self.finding_count,
            "category_scores": self.category_scores,
            "severity_distribution": self.severity_distribution,
            "findings_by_category": self.findings_by_category,
        }


# Severity weights for penalty calculation
SEVERITY_WEIGHTS = {
    FindingSeverity.INFO: 1.0,
    FindingSeverity.WARNING: 2.0,
    FindingSeverity.ERROR: 4.0,
    FindingSeverity.CRITICAL: 8.0,
}

# Additional flat penalty contribution by severity, so single findings
# at different severities always produce distinguishable scores.
SEVERITY_BONUS = {
    FindingSeverity.INFO: 0.0,
    FindingSeverity.WARNING: 1.0,
    FindingSeverity.ERROR: 3.0,
    FindingSeverity.CRITICAL: 8.0,
}

# Category weights (must sum to 1.0)
CATEGORY_WEIGHTS = {
    FindingCategory.COMPLEXITY: 0.30,
    FindingCategory.STALENESS: 0.25,
    FindingCategory.SECURITY: 0.25,
    FindingCategory.DUPLICATION: 0.10,
    FindingCategory.TESTING: 0.10,
    FindingCategory.MAINTAINABILITY: 0.10,  # Default bucket
}

# Score boundaries
PERFECT_SCORE = 850
MINIMUM_SCORE = 300
MAX_PENALTY = PERFECT_SCORE - MINIMUM_SCORE  # 550 points available


def calculate_score(findings: list[Finding]) -> ScoringResult:
    """Calculate deterministic code quality score from findings.

    Score formula:
        score = 850 - weighted_penalty
        where weighted_penalty = sum(category_penalty * category_weight)

    Args:
        findings: List of normalized findings from all analyzers

    Returns:
        ScoringResult with score, grade, and breakdown
    """
    # Handle empty case
    if not findings:
        return ScoringResult(
            score=PERFECT_SCORE,
            grade="A",
            total_debt_points=0,
            finding_count=0,
            category_scores={cat.value: PERFECT_SCORE for cat in FindingCategory},
            severity_distribution={sev.value: 0 for sev in FindingSeverity},
            findings_by_category={cat.value: 0 for cat in FindingCategory},
        )

    # Group findings by category
    findings_by_category_map: dict[FindingCategory, list[Finding]] = defaultdict(list)
    for finding in findings:
        findings_by_category_map[finding.category].append(finding)

    # Calculate total debt points
    total_debt_points = sum(f.debt_points for f in findings)

    # Calculate severity distribution
    severity_counts: dict[str, int] = {sev.value: 0 for sev in FindingSeverity}
    for finding in findings:
        severity_counts[finding.severity.value] += 1

    # Calculate category penalties
    category_penalties: dict[FindingCategory, float] = {}
    for category in FindingCategory:
        category_findings = findings_by_category_map.get(category, [])
        penalty = _calculate_category_penalty(category_findings)
        category_penalties[category] = penalty

    # Calculate weighted total penalty
    total_penalty = sum(
        category_penalties.get(cat, 0.0) * CATEGORY_WEIGHTS.get(cat, 0.0)
        for cat in FindingCategory
    )

    # Calculate final score (clamped to valid range)
    raw_score = PERFECT_SCORE - total_penalty
    final_score = max(MINIMUM_SCORE, min(PERFECT_SCORE, int(raw_score)))

    # Calculate category scores (reverse the penalty for display)
    category_scores = {
        cat.value: max(
            MINIMUM_SCORE,
            min(PERFECT_SCORE, int(PERFECT_SCORE - category_penalties.get(cat, 0.0))),
        )
        for cat in FindingCategory
    }

    # Calculate findings count by category
    findings_count_by_category = {
        cat.value: len(findings_by_category_map.get(cat, [])) for cat in FindingCategory
    }

    # Determine grade
    grade = _score_to_grade(final_score)

    return ScoringResult(
        score=final_score,
        grade=grade,
        total_debt_points=total_debt_points,
        finding_count=len(findings),
        category_scores=category_scores,
        severity_distribution=severity_counts,
        findings_by_category=findings_count_by_category,
    )


def _calculate_category_penalty(findings: list[Finding]) -> float:
    """Calculate penalty for a single category.

    Penalty is based on:
    - Debt points (primary driver)
    - Severity weighting
    - Finding count

    Returns:
        Penalty value (0 to MAX_PENALTY)
    """
    if not findings:
        return 0.0

    # Calculate weighted debt
    weighted_debt = sum(
        f.debt_points * SEVERITY_WEIGHTS.get(f.severity, 1.0) for f in findings
    )

    # Severity bonus ensures single findings at different severities produce
    # distinguishable scores even when debt_points are small.
    severity_bonus = sum(
        SEVERITY_BONUS.get(f.severity, 0.0) for f in findings
    )

    # Normalize to 0-MAX_PENALTY range
    # Scale factor adjusts sensitivity (lower = more sensitive to debt)
    scale_factor = 1.0
    penalty = min(MAX_PENALTY, (weighted_debt + severity_bonus) / scale_factor)

    return penalty


def _score_to_grade(score: int) -> str:
    """Convert numeric score to letter grade.

    Grading scale (FICO-like):
        800-850: A (Excellent)
        740-799: B (Very Good)
        670-739: C (Good)
        580-669: D (Fair)
        300-579: F (Poor)
    """
    if score >= 800:
        return "A"
    elif score >= 740:
        return "B"
    elif score >= 670:
        return "C"
    elif score >= 580:
        return "D"
    else:
        return "F"
