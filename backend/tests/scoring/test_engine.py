"""Tests for scoring engine.

This is a stub for future scoring engine tests.
Once VP Engineering implements the scoring engine, these tests will verify:
- Deterministic scoring (same findings → same score)
- Score calculation consistency
- Debt points aggregation
- Category weighting
- Score normalization (0-1000 range)
"""


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
        from app.models.finding import FindingSeverity
        from app.scoring.engine import calculate_score

        info = sample_findings_fixture[0].model_copy(deep=True)
        info.severity = FindingSeverity.INFO
        critical = sample_findings_fixture[0].model_copy(deep=True)
        critical.severity = FindingSeverity.CRITICAL
        critical.id = "finding_critical"
        r_info = calculate_score([info])
        r_critical = calculate_score([critical])
        assert r_critical.score < r_info.score

    def test_category_weighting_runs(self, sample_findings_fixture):
        from app.models.finding import FindingCategory
        from app.scoring.engine import calculate_score

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

    def test_fixing_any_finding_raises_score_no_dead_zones(self):
        """Every fixed finding must visibly raise the score.

        Regression test for the product requirement that a rescan after a
        fix reflects the fix. Builds a finding-dense category (the old
        logarithmic cap flattened marginal impact to zero here) and asserts
        that removing any single finding strictly increases the score.
        """
        from app.models.finding import Finding, FindingCategory, FindingSeverity
        from app.scoring.engine import calculate_score

        findings: list[Finding] = []
        for i in range(40):
            findings.append(
                Finding(
                    id=f"dead_zone_{i}",
                    rule_id="testing_debt:untested-module",
                    category=FindingCategory.TESTING,
                    severity=FindingSeverity.CRITICAL,
                    confidence=1.0,
                    file_path=f"src/mod_{i}.py",
                    line_start=1,
                    line_end=1,
                    symbol=None,
                    evidence="no test file",
                    message="untested module",
                    suggestion="add tests",
                    debt_points=12,
                    remediation_effort="1 hour",
                    analyzer="testing_debt",
                    metadata={},
                )
            )
        before = calculate_score(findings)
        assert before.score > 300, "test must not start at the score floor"
        for victim in (findings[0], findings[20], findings[-1]):
            remaining = [f for f in findings if f.id != victim.id]
            after = calculate_score(remaining)
            assert after.score > before.score, (
                f"removing {victim.id} did not raise the score ({before.score} -> {after.score})"
            )
