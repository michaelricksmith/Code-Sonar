"""Deterministic technical-debt scoring for Code Sonar.

The score is authoritative and reproducible. Each finding contributes based on
its analyzer debt points, severity, confidence, category, and repository-path
context. Source/test/fixture context is applied per finding. Non-production
contributions are additionally bounded within each category so intentionally
large test suites and fixtures cannot overwhelm real production findings.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import fsum, log1p
from typing import Any

from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.security.path_classifier import FIXTURE, SOURCE, TEST, classify_path

SCORING_VERSION: str = "1.1"


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
        penalty_explanation: dict[str, Any],
    ):
        self.score = score
        self.grade = grade
        self.total_debt_points = total_debt_points
        self.finding_count = finding_count
        self.category_scores = category_scores
        self.severity_distribution = severity_distribution
        self.findings_by_category = findings_by_category
        self.findings_source_breakdown = findings_source_breakdown
        self.penalty_explanation = penalty_explanation

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
            "penalty_explanation": self.penalty_explanation,
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
    _raise_for_duplicate_ids(findings)

    if not findings:
        return _empty_scoring_result()

    canonical_findings = sorted(findings, key=lambda finding: finding.id)
    findings_by_category_map = _group_by_category(canonical_findings)

    total_debt_points = sum(f.debt_points for f in canonical_findings)

    category_details = _category_details(findings_by_category_map)
    category_penalties = _category_penalties(category_details)

    total_penalty = _weighted_total_penalty(category_penalties)
    final_score = _clamp_score(PERFECT_SCORE - total_penalty)

    return ScoringResult(
        score=final_score,
        grade=_score_to_grade(final_score),
        total_debt_points=total_debt_points,
        finding_count=len(canonical_findings),
        category_scores=_category_scores(category_penalties),
        severity_distribution=_severity_distribution(canonical_findings),
        findings_by_category={
            cat.value: len(findings_by_category_map.get(cat, [])) for cat in FindingCategory
        },
        findings_source_breakdown=_source_breakdown(canonical_findings),
        penalty_explanation=_penalty_explanation(
            category_details, category_penalties, total_penalty, canonical_findings
        ),
    )


def _raise_for_duplicate_ids(findings: list[Finding]) -> None:
    finding_ids = [finding.id for finding in findings]
    duplicate_ids = sorted(item for item, count in Counter(finding_ids).items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"Duplicate finding IDs are not scoreable: {', '.join(duplicate_ids)}")


def _empty_scoring_result() -> ScoringResult:
    return ScoringResult(
        score=PERFECT_SCORE,
        grade="A",
        total_debt_points=0,
        finding_count=0,
        category_scores={cat.value: PERFECT_SCORE for cat in FindingCategory},
        severity_distribution={sev.value: 0 for sev in FindingSeverity},
        findings_by_category={cat.value: 0 for cat in FindingCategory},
        findings_source_breakdown={k: 0 for k in SOURCE_CONTEXT_MODIFIER},
        penalty_explanation={
            "total_penalty": 0.0,
            "categories": {},
            "findings": [],
        },
    )


def _group_by_category(
    findings: list[Finding],
) -> dict[FindingCategory, list[Finding]]:
    grouped: dict[FindingCategory, list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.category].append(finding)
    return grouped


def _category_details(
    findings_by_category_map: dict[FindingCategory, list[Finding]],
) -> dict[FindingCategory, dict[str, float | bool]]:
    return {
        category: _calculate_category_penalty(findings_by_category_map.get(category, []))
        for category in FindingCategory
    }


def _category_penalties(
    category_details: dict[FindingCategory, dict[str, float | bool]],
) -> dict[FindingCategory, float]:
    return {
        category: float(details["capped_penalty"]) for category, details in category_details.items()
    }


def _weighted_total_penalty(category_penalties: dict[FindingCategory, float]) -> float:
    return fsum(
        category_penalties.get(cat, 0.0) * CATEGORY_WEIGHTS.get(cat, 0.0) for cat in FindingCategory
    )


def _clamp_score(raw_score: float) -> int:
    return max(MINIMUM_SCORE, min(PERFECT_SCORE, int(raw_score)))


def _category_scores(category_penalties: dict[FindingCategory, float]) -> dict[str, int]:
    return {
        cat.value: _clamp_score(PERFECT_SCORE - category_penalties.get(cat, 0.0))
        for cat in FindingCategory
    }


def _severity_distribution(findings: list[Finding]) -> dict[str, int]:
    severity_counts: dict[str, int] = {sev.value: 0 for sev in FindingSeverity}
    for finding in findings:
        severity_counts[finding.severity.value] += 1
    return severity_counts


def _source_breakdown(findings: list[Finding]) -> dict[str, int]:
    source_counts: dict[str, int] = {k: 0 for k in SOURCE_CONTEXT_MODIFIER}
    for finding in findings:
        cls = classify_path(finding.file_path)
        source_counts[cls if cls in source_counts else SOURCE] += 1
    return source_counts


def _penalty_explanation(
    category_details: dict[FindingCategory, dict[str, float | bool]],
    category_penalties: dict[FindingCategory, float],
    total_penalty: float,
    findings: list[Finding],
) -> dict[str, Any]:
    return {
        "total_penalty": total_penalty,
        "categories": {
            category.value: {
                **details,
                "weight": CATEGORY_WEIGHTS.get(category, 0.0),
                "weighted_penalty": category_penalties[category]
                * CATEGORY_WEIGHTS.get(category, 0.0),
            }
            for category, details in category_details.items()
        },
        "findings": [_finding_explanation(finding) for finding in findings],
    }


def _confidence_modifier(finding: Finding) -> float:
    if finding.confidence < LOW_CONFIDENCE_THRESHOLD:
        return LOW_CONFIDENCE_MODIFIER
    return 1.0


def _finding_explanation(finding: Finding) -> dict[str, Any]:
    severity_weight = SEVERITY_WEIGHTS.get(finding.severity, 1.0)
    confidence_modifier = _confidence_modifier(finding)
    path_class = classify_path(finding.file_path)
    context_modifier = SOURCE_CONTEXT_MODIFIER.get(path_class, 1.0)
    severity_bonus = SEVERITY_BONUS.get(finding.severity, 0.0)
    weighted_debt_penalty = finding.debt_points * severity_weight
    confidence_adjusted_penalty = weighted_debt_penalty * confidence_modifier + severity_bonus
    return {
        "finding_id": finding.id,
        "analyzer": finding.analyzer,
        "category": finding.category.value,
        "path_class": path_class,
        "debt_points": finding.debt_points,
        "severity_weight": severity_weight,
        "severity_bonus": severity_bonus,
        "confidence_modifier": confidence_modifier,
        "context_modifier": context_modifier,
        "weighted_debt_penalty": weighted_debt_penalty,
        "confidence_adjusted_penalty": confidence_adjusted_penalty,
        "effective_penalty": confidence_adjusted_penalty * context_modifier,
    }


def _calculate_category_penalty(findings: list[Finding]) -> dict[str, float | bool]:
    """Calculate a bounded category penalty with per-finding context weighting.

    Production and non-production contributions are accumulated separately.
    Test/fixture findings still receive their 0.25 per-finding modifier, and
    their aggregate contribution is capped at 25% of the category's available
    penalty. This prevents intentionally repetitive fixtures from dominating a
    repository's score while leaving their raw findings and debt visible.
    """
    if not findings:
        return {
            "source_penalty": 0.0,
            "non_source_penalty": 0.0,
            "bounded_non_source_penalty": 0.0,
            "non_source_cap_applied": False,
            "category_cap_applied": False,
            "capped_penalty": 0.0,
        }

    explanations = [_finding_explanation(finding) for finding in findings]
    source_penalty = fsum(
        float(item["effective_penalty"]) for item in explanations if item["path_class"] == SOURCE
    )
    non_source_penalty = fsum(
        float(item["effective_penalty"]) for item in explanations if item["path_class"] != SOURCE
    )

    bounded_non_source = min(NON_SOURCE_CATEGORY_CAP, non_source_penalty)
    combined = source_penalty + bounded_non_source
    # Responsive cap: linear up to MAX_PENALTY, then logarithmic growth.
    # A hard cap created dead zones where fixing issues didn't move the
    # score; this keeps every fix meaningful while preventing huge
    # finding counts from linearly exploding the penalty.
    if combined <= MAX_PENALTY:
        capped = combined
        cap_applied = False
    else:
        capped = MAX_PENALTY + MAX_PENALTY * 0.1 * log1p((combined - MAX_PENALTY) / MAX_PENALTY)
        cap_applied = True
    return {
        "source_penalty": source_penalty,
        "non_source_penalty": non_source_penalty,
        "bounded_non_source_penalty": bounded_non_source,
        "non_source_cap_applied": non_source_penalty > NON_SOURCE_CATEGORY_CAP,
        "category_cap_applied": cap_applied,
        "capped_penalty": capped,
    }


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
