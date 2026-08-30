"""Stable, versioned feature-vector schema for Code Sonar ML."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FEATURE_SCHEMA_VERSION: str = "1.0"


@dataclass(frozen=True, slots=True)
class ScanFeatureVector:
    """Deterministic scan-level ML features.

    The order returned by :meth:`ordered_values` is part of the v1.0 contract.
    Adding, removing, reordering, rescaling, or changing the meaning of a feature
    requires a new ``FEATURE_SCHEMA_VERSION``.
    """

    score: float
    total_debt_points: float
    finding_count: float
    severity_info: float
    severity_warning: float
    severity_error: float
    severity_critical: float
    category_complexity: float
    category_staleness: float
    category_security: float
    category_duplication: float
    category_testing: float
    category_maintainability: float
    source_findings: float
    test_findings: float
    fixture_findings: float
    mean_confidence: float
    mean_debt_points: float
    max_finding_risk: float
    analyzer_diversity: float

    @classmethod
    def feature_names(cls) -> tuple[str, ...]:
        return (
            "score",
            "total_debt_points",
            "finding_count",
            "severity_info",
            "severity_warning",
            "severity_error",
            "severity_critical",
            "category_complexity",
            "category_staleness",
            "category_security",
            "category_duplication",
            "category_testing",
            "category_maintainability",
            "source_findings",
            "test_findings",
            "fixture_findings",
            "mean_confidence",
            "mean_debt_points",
            "max_finding_risk",
            "analyzer_diversity",
        )

    def ordered_values(self) -> tuple[float, ...]:
        return (
            self.score,
            self.total_debt_points,
            self.finding_count,
            self.severity_info,
            self.severity_warning,
            self.severity_error,
            self.severity_critical,
            self.category_complexity,
            self.category_staleness,
            self.category_security,
            self.category_duplication,
            self.category_testing,
            self.category_maintainability,
            self.source_findings,
            self.test_findings,
            self.fixture_findings,
            self.mean_confidence,
            self.mean_debt_points,
            self.max_finding_risk,
            self.analyzer_diversity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "features": dict(zip(self.feature_names(), self.ordered_values(), strict=True)),
        }
