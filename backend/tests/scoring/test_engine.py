"""Tests for scoring engine.

This is a stub for future scoring engine tests.
Once VP Engineering implements the scoring engine, these tests will verify:
- Deterministic scoring (same findings → same score)
- Score calculation consistency
- Debt points aggregation
- Category weighting
- Score normalization (0-1000 range)
"""

import pytest

from app.models.finding import Finding


class TestScoringEngine:
    """Test suite for scoring engine (stub for future implementation)."""

    def test_deterministic_scoring(self, sample_findings_fixture):
        from app.scoring.engine import calculate_score
        r1 = calculate_score(sample_findings_fixture)
        r2 = calculate_score(sample_findings_fixture)
        assert r1.score == r2.score
        assert r1.grade == r2.grade
        assert r1.total_debt_points == r2.total_debt_points

    def test_score_range_300_to_850(self, sample_findings_fixture):
        from app.scoring.engine import calculate_score
        r = calculate_score(sample_findings_fixture)
        assert 300 <= r.score <= 850

    def test_empty_findings_returns_perfect_score(self):
        from app.scoring.engine import calculate_score
        r = calculate_score([])
        assert r.score == 850
        assert r.grade == "A"

    def test_debt_points_lower_score(self, sample_findings_fixture):
        from app.scoring.engine import calculate_score
        with_findings = calculate_score(sample_findings_fixture)
        perfect = calculate_score([])
        assert with_findings.score < perfect.score

    def test_severity_affects_score(self, sample_findings_fixture):
        from app.scoring.engine import calculate_score
        from app.models.finding import FindingSeverity
        info = sample_findings_fixture[0].model_copy(deep=True)
        info.severity = FindingSeverity.INFO
        critical = sample_findings_fixture[0].model_copy(deep=True)
        critical.severity = FindingSeverity.CRITICAL
        critical.id = "finding_critical"
        r_info = calculate_score([info])
        r_critical = calculate_score([critical])
        assert r_critical.score < r_info.score

    def test_category_weighting_runs(self, sample_findings_fixture):
        from app.scoring.engine import calculate_score
        from app.models.finding import FindingCategory
        sec = sample_findings_fixture[0].model_copy(deep=True)
        sec.category = FindingCategory.SECURITY
        sec.id = "security_001"
        maint = sample_findings_fixture[0].model_copy(deep=True)
        maint.category = FindingCategory.MAINTAINABILITY
        maint.id = "maintainability_001"
        r_sec = calculate_score([sec])
        r_maint = calculate_score([maint])
        assert 300 <= r_sec.score <= 850
        assert 300 <= r_maint.score <= 850

    def test_breakdown_has_category_scores(self, sample_findings_fixture):
        from app.scoring.engine import calculate_score
        r = calculate_score(sample_findings_fixture)
        assert "complexity" in r.category_scores
        assert "security" in r.category_scores
        assert "maintainability" in r.category_scores
