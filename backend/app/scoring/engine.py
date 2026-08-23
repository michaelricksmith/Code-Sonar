"""Deterministic scoring engine for Code Sonar.

Calculates technical debt scores from normalized findings.
Score range: 300-850 (FICO-like scale).

============================================================
SCORING RATIONALE (Checkpoint 5 audit; not a target rebalance)
============================================================

The model has four inputs:

  1. finding.debt_points        (analyzer-assigned; integer)
  2. finding.severity           (info | warning | error | critical)
  3. finding.confidence         (0.0–1.0)
  4. finding.category            (one of FindingCategory enum)

And one new context input (Checkpoint 5):

  5. path classification         (source | test | fixture)

The final penalty per finding is:

    finding_penalty  =  debt_points
                      * SEVERITY_WEIGHT[severity]
                      * CATEGORY_WEIGHT[category]
                      * CONFIDENCE_MODIFIER[confidence_bucket]
                      * SOURCE_CONTEXT_MODIFIER[path_class]

plus a flat SEVERITY_BONUS[severity] to keep single-finding scores
distinguishable at the low end of the scale.

--------------------------------------
(1) Severity mathematical effect
--------------------------------------

Each severity multiplies the underlying debt by a constant and adds a
flat bonus. The bonus is what guarantees that a single CRITICAL
finding (debt_points=10) scores meaningfully below a single INFO
finding (debt_points=1), even though the multipliers alone would
collide near zero:

    INFO     -> x 1.0 + 0.0
    WARNING  -> x 2.0 + 1.0
    ERROR    -> x 4.0 + 3.0
    CRITICAL -> x 8.0 + 8.0

The doubling pattern (1, 2, 4, 8) means each severity step roughly
doubles the per-finding contribution. The flat bonus keeps low-severity
findings from being rounded into invisibility at the bottom of the
300–850 range.

--------------------------------------
(2) Category weighting rationale
--------------------------------------

Categories have weights chosen by *risk class*, not by finding volume:

    COMPLEXITY      = 0.30  (predictor of bug density)
    STALENESS       = 0.25  (predictor of maintenance burden)
    SECURITY        = 0.25  (predictor of incident severity)
    DUPLICATION     = 0.10  (correlate of refactor friction)
    TESTING         = 0.10  (correlate of regression risk)
    MAINTAINABILITY = 0.10  (default bucket; tightly correlated
                             with COMPLEXITY but kept separate so
                             analyzers that don't fit the precise
                             categories above still surface)

These weights are *predictors*, not multipliers. A SECURITY finding
weighs the same as a COMPLEXITY finding at equal debt points; the
weights only scale the within-category penalty. The category weights
are stable across releases and recorded here so that the rationale is
reproducible and explainable without re-running the model.

Sum = 1.20 (not 1.0). This is intentional: weights reflect the
risk-correlation of each category, but the final penalty is bounded
by ``MAX_PENALTY`` (= 550) and clamped by the score floor (300).
Categories can overlap (COMPLEXITY and MAINTAINABILITY often
co-occur) and the extra headroom keeps the model from saturating
in single-category repositories. This is a documented choice, not a
bug. The clamping in ``calculate_score`` prevents unbounded scores.

--------------------------------------
(3) SECURITY does not auto-dominate fixture secrets
--------------------------------------

The Checkpoint 5 source-vs-fixture classifier (see
``app.security.path_classifier``) classifies each finding's path as
``source``, ``test``, or ``fixture``. A finding whose file is
``tests/``, ``examples/``, or a ``.env.example`` documentation file
is treated as a fixture.

Fixture findings receive a SOURCE_CONTEXT_MODIFIER of 0.25, meaning
they contribute 25% as much to the final score as the same finding
in production source. This is a **context modifier** — it does not
suppress the finding, does not hide it from the API, and does not
hide it from the UI. The finding still appears with its original
debt_points in the JSON output and on the dashboard. Only the
*score impact* is muted, so that a test fixture containing
intentional `AKIAIOSFODNN7EXAMPLE`-style tokens does not push a
production-clean codebase into D/F territory.

This is **not** a `secrets_multiplier` (Michael, 18:28 PDT). The
modifier is symmetric — it would mute any fixture-context finding,
not just secrets — and it does not increase Code Sonar's own score;
it only changes how findings on fixture paths *count* toward the
score.

--------------------------------------
(4) Production vs fixture distinction
--------------------------------------

``app.security.path_classifier.classify_path(rel_path)`` returns one
of ``SOURCE | TEST | FIXTURE``. The scoring engine reads this and
applies the modifier via:

    SOURCE_CONTEXT_MODIFIER = {
        "source":  1.0,   # full contribution
        "test":    0.25,  # tests intentionally exercise error paths
        "fixture": 0.25,  # documentation examples are not live debt
    }

The two non-source modifiers are intentionally equal so that any
"non-production" classification gets the same discount.

--------------------------------------
(5) Confidence modifier (lightweight, not arbitrary)
--------------------------------------

Findings with confidence < 0.7 receive a 0.5x modifier. This
reflects that the analyzer itself expressed uncertainty. The
threshold matches the confidence floor used by ``testing_debt``
(0.7) and ``secrets`` named kinds (>= 0.85). It is intentionally
conservative — only findings whose analyzer already reported
weak confidence are dampened.

--------------------------------------
Determinism
--------------------------------------

The engine is pure: same input -> same output. No time, random, or
filesystem-derived state enters the calculation. The ordering of
findings in the input list does not affect the score (only the
category/severity/confidence/path attributes are read). See
``backend/tests/scoring/test_engine.py`` and
``backend/tests/scoring/test_calibration.py`` for ordering
invariants.
"""

from collections import defaultdict
from typing import Any

from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.security.path_classifier import (
    FIXTURE,
    SOURCE,
    TEST,
    classify_path,
)


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
        """Convert to dictionary for API serialization."""
        return {
            "score": self.score,
            "grade": self.grade,
            "total_debt_points": self.total_debt_points,
            "finding_count": self.finding_count,
            "category_scores": self.category_scores,
            "severity_distribution": self.severity_distribution,
            "findings_by_category": self.findings_by_category,
            "findings_source_breakdown": self.findings_source_breakdown,
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

# Category weights. Sum = 1.20 (see module docstring §2 for rationale).
CATEGORY_WEIGHTS = {
    FindingCategory.COMPLEXITY: 0.30,
    FindingCategory.STALENESS: 0.25,
    FindingCategory.SECURITY: 0.25,
    FindingCategory.DUPLICATION: 0.10,
    FindingCategory.TESTING: 0.10,
    FindingCategory.MAINTAINABILITY: 0.10,
}

# Source-context modifier (Checkpoint 5; see module docstring §3-4).
SOURCE_CONTEXT_MODIFIER: dict[str, float] = {
    SOURCE: 1.0,
    TEST: 0.25,
    FIXTURE: 0.25,
}

# Confidence threshold below which a finding's contribution is halved.
LOW_CONFIDENCE_THRESHOLD: float = 0.7
LOW_CONFIDENCE_MODIFIER: float = 0.5

# Score boundaries
PERFECT_SCORE = 850
MINIMUM_SCORE = 300
MAX_PENALTY = PERFECT_SCORE - MINIMUM_SCORE  # 550 points available


def calculate_score(findings: list[Finding]) -> ScoringResult:
    """Calculate deterministic code quality score from findings.

    Score formula:
        score = 850 - weighted_penalty
        where weighted_penalty = sum(category_penalty * category_weight)
        and each per-finding penalty is multiplied by SEVERITY_WEIGHT,
        CATEGORY_WEIGHT, CONFIDENCE_MODIFIER, and SOURCE_CONTEXT_MODIFIER.

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
            findings_source_breakdown={k: 0 for k in SOURCE_CONTEXT_MODIFIER},
        )

    # Group findings by category
    findings_by_category_map: dict[FindingCategory, list[Finding]] = defaultdict(list)
    for finding in findings:
        findings_by_category_map[finding.category].append(finding)

    # Total debt points is the *unmodified* sum reported by analyzers.
    # The source-context modifier only affects the *score*, not the
    # reported debt total — the dashboard surfaces raw debt so users
    # see the actual analyzer-reported burden regardless of context.
    total_debt_points = sum(f.debt_points for f in findings)

    # Calculate severity distribution
    severity_counts: dict[str, int] = {sev.value: 0 for sev in FindingSeverity}
    for finding in findings:
        severity_counts[finding.severity.value] += 1

    # Track source breakdown for the dashboard's "why the score
    # changed" callout.
    source_counts: dict[str, int] = {k: 0 for k in SOURCE_CONTEXT_MODIFIER}
    for finding in findings:
        cls = classify_path(finding.file_path)
        if cls not in source_counts:
            source_counts[SOURCE] += 1  # any unknown classification treated as source
        else:
            source_counts[cls] += 1

    # Calculate category penalties. Per-finding modifiers (severity,
    # confidence) are applied here. The source-context modifier is
    # applied AFTER aggregation so that bulk test fixtures cannot
    # outrank a few production findings: a category containing only
    # test/fixture paths receives the discount on the *whole* category
    # penalty, not on each finding individually. This preserves the
    # principle that SECURITY cannot dominate via fixtures even when
    # fixtures contain many high-debt findings.
    category_penalties: dict[FindingCategory, float] = {}
    for category in FindingCategory:
        category_findings = findings_by_category_map.get(category, [])
        raw_penalty = _calculate_category_penalty(category_findings)
        if not category_findings:
            category_penalties[category] = 0.0
            continue
        # Determine the dominant source-context for this category: if
        # every finding in the category is fixture/test, apply the
        # discount. Otherwise the category is treated as production.
        all_fixture = all(
            classify_path(f.file_path) in (TEST, FIXTURE)
            for f in category_findings
        )
        modifier = (
            SOURCE_CONTEXT_MODIFIER[TEST] if all_fixture else 1.0
        )
        category_penalties[category] = raw_penalty * modifier

    # Calculate weighted total penalty.
    total_penalty = sum(
        category_penalties.get(cat, 0.0) * CATEGORY_WEIGHTS.get(cat, 0.0)
        for cat in FindingCategory
    )

    # Calculate final score (clamped to valid range).
    raw_score = PERFECT_SCORE - total_penalty
    final_score = max(MINIMUM_SCORE, min(PERFECT_SCORE, int(raw_score)))

    # Calculate category scores (reverse the penalty for display).
    category_scores = {
        cat.value: max(
            MINIMUM_SCORE,
            min(PERFECT_SCORE, int(PERFECT_SCORE - category_penalties.get(cat, 0.0))),
        )
        for cat in FindingCategory
    }

    # Calculate findings count by category.
    findings_count_by_category = {
        cat.value: len(findings_by_category_map.get(cat, [])) for cat in FindingCategory
    }

    # Determine grade.
    grade = _score_to_grade(final_score)

    return ScoringResult(
        score=final_score,
        grade=grade,
        total_debt_points=total_debt_points,
        finding_count=len(findings),
        category_scores=category_scores,
        severity_distribution=severity_counts,
        findings_by_category=findings_count_by_category,
        findings_source_breakdown=source_counts,
    )


def _context_modifier(finding: Finding) -> float:
    """Return the source-context modifier for a finding's path."""
    return SOURCE_CONTEXT_MODIFIER.get(classify_path(finding.file_path), 1.0)


def _confidence_modifier(finding: Finding) -> float:
    """Halve the contribution of low-confidence findings."""
    if finding.confidence < LOW_CONFIDENCE_THRESHOLD:
        return LOW_CONFIDENCE_MODIFIER
    return 1.0


def _calculate_category_penalty(findings: list[Finding]) -> float:
    """Calculate penalty for a single category (pre source-context modifier).

    Each finding contributes:
        debt_points * SEVERITY_WEIGHTS[severity]
                    * CONFIDENCE_MODIFIER(confidence)
    plus a flat SEVERITY_BONUS[severity].

    The result is bounded by ``MAX_PENALTY`` (550). The caller
    (``calculate_score``) applies the source-context modifier at
    category level after this aggregation, so that bulk fixture
    findings cannot outrank a few production findings.

    Args:
        findings: Findings in this category.

    Returns:
        Penalty value (0 to MAX_PENALTY).
    """
    if not findings:
        return 0.0

    weighted_debt = 0.0
    severity_bonus = 0.0
    for f in findings:
        sev_w = SEVERITY_WEIGHTS.get(f.severity, 1.0)
        conf_m = _confidence_modifier(f)
        weighted_debt += f.debt_points * sev_w * conf_m
        severity_bonus += SEVERITY_BONUS.get(f.severity, 0.0)

    penalty = min(MAX_PENALTY, weighted_debt + severity_bonus)
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
