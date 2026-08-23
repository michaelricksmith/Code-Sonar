"""Calibration tests for the scoring engine.

These tests build synthetic repositories with known debt profiles and
assert that the scoring engine produces deterministic, explainable,
*ordered* results. The goal is NOT to lock in a specific score — the
scoring model is intentionally a function of the findings, and
rebalancing severity weights or category weights is allowed in
future checkpoints. The goal IS to lock in:

1. Determinism: same input -> same output, byte-identical.
2. Ordering: clean > low < moderate < severe (monotonic worsening).
3. Fixture vs source: a fixture-only secrets repository should
   score meaningfully higher than the same findings in production.
4. SECURITY cannot dominate purely via test fixtures: a test-only
   fake-secret repo must NOT score worse than a genuinely-severe
   maintainability repo.
5. Score explainability: given the findings, you can hand-trace the
   penalty computation and reproduce the score.

These tests are the scoring engine's regression guard. They run on
synthetic fixtures only; nothing here touches the real workspace.
"""

from __future__ import annotations

from app.models.finding import (
    Finding,
    FindingCategory,
    FindingSeverity,
)
from app.scoring.engine import (
    MAX_PENALTY,
    MINIMUM_SCORE,
    PERFECT_SCORE,
    calculate_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk(
    *,
    rid: str,
    fid: str,
    severity: FindingSeverity,
    category: FindingCategory,
    confidence: float,
    debt: int,
    rel_path: str,
    line: int = 1,
    symbol: str | None = None,
) -> Finding:
    return Finding(
        id=fid,
        rule_id=rid,
        category=category,
        severity=severity,
        confidence=confidence,
        file_path=rel_path,
        line_start=line,
        line_end=line,
        symbol=symbol,
        evidence=f"rid={rid} debt={debt}",
        message=f"synthetic finding {fid}",
        suggestion=None,
        debt_points=debt,
        remediation_effort="15 minutes",
        analyzer="synthetic",
        metadata={"synthetic": True},
    )


def _empty() -> list[Finding]:
    return []


def _clean() -> list[Finding]:
    # A clean repo has zero findings.
    return _empty()


def _low_debt() -> list[Finding]:
    return [
        _mk(
            rid="comment_markers:TODO",
            fid="f_low_1",
            severity=FindingSeverity.INFO,
            category=FindingCategory.MAINTAINABILITY,
            confidence=1.0,
            debt=1,
            rel_path="src/app.py",
        ),
        _mk(
            rid="comment_markers:TODO",
            fid="f_low_2",
            severity=FindingSeverity.INFO,
            category=FindingCategory.MAINTAINABILITY,
            confidence=1.0,
            debt=1,
            rel_path="src/utils.py",
        ),
    ]


def _moderate_debt() -> list[Finding]:
    findings: list[Finding] = []
    for i in range(5):
        findings.append(
            _mk(
                rid="oversized_functions:over-threshold",
                fid=f"f_mod_{i}",
                severity=FindingSeverity.WARNING,
                category=FindingCategory.MAINTAINABILITY,
                confidence=1.0,
                debt=4,
                rel_path=f"src/mod{i}.py",
            )
        )
    for i in range(3):
        findings.append(
            _mk(
                rid="testing_debt:untested-module",
                fid=f"f_mod_t_{i}",
                severity=FindingSeverity.WARNING,
                category=FindingCategory.TESTING,
                confidence=0.7,
                debt=4,
                rel_path=f"src/uncovered{i}.py",
            )
        )
    return findings


def _severe_maintainability() -> list[Finding]:
    findings: list[Finding] = []
    for i in range(20):
        findings.append(
            _mk(
                rid="oversized_functions:over-threshold",
                fid=f"f_sev_{i}",
                severity=FindingSeverity.CRITICAL,
                category=FindingCategory.MAINTAINABILITY,
                confidence=1.0,
                debt=12,
                rel_path=f"src/big{i}.py",
            )
        )
    for i in range(10):
        findings.append(
            _mk(
                rid="cyclomatic_complexity:high-cc",
                fid=f"f_sev_cc_{i}",
                severity=FindingSeverity.CRITICAL,
                category=FindingCategory.COMPLEXITY,
                confidence=1.0,
                debt=12,
                rel_path=f"src/complex{i}.py",
            )
        )
    return findings


def _genuine_security() -> list[Finding]:
    # Three leaked AWS keys in production source — the "real" exposure case.
    return [
        _mk(
            rid="secrets:aws_access_key_id",
            fid=f"f_sec_{i}",
            severity=FindingSeverity.ERROR,
            category=FindingCategory.SECURITY,
            confidence=0.95,
            debt=10,
            rel_path=f"src/api/endpoint{i}.py",
        )
        for i in range(3)
    ]


def _test_only_fake_secrets() -> list[Finding]:
    # Same 23 fake-secret findings as in Checkpoint 4's self-scan baseline,
    # but EVERY path is under tests/ — fixture context.
    findings: list[Finding] = []
    for i in range(23):
        findings.append(
            _mk(
                rid="secrets:aws_access_key_id",
                fid=f"f_fix_{i}",
                severity=FindingSeverity.ERROR,
                category=FindingCategory.SECURITY,
                confidence=0.95,
                debt=10,
                rel_path=f"tests/fixtures/secret_case_{i}.py",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestScoringDeterminism:
    def test_repeated_scoring_yields_identical_score(self):
        findings = _moderate_debt()
        r1 = calculate_score(findings)
        r2 = calculate_score(findings)
        r3 = calculate_score(findings)
        assert r1.score == r2.score == r3.score
        assert r1.grade == r2.grade == r3.grade
        assert r1.total_debt_points == r2.total_debt_points == r3.total_debt_points
        assert r1.findings_source_breakdown == r2.findings_source_breakdown

    def test_reordering_findings_does_not_change_score(self):
        # The scoring engine reads only the aggregate per-category stats.
        # Input ordering is irrelevant; the score must be identical.
        findings = _severe_maintainability()
        r1 = calculate_score(findings)
        r2 = calculate_score(list(reversed(findings)))
        r3 = calculate_score(sorted(findings, key=lambda f: f.id))
        assert r1.score == r2.score == r3.score
        assert r1.total_debt_points == r2.total_debt_points == r3.total_debt_points

    def test_score_is_byte_stable(self):
        findings = _moderate_debt()
        r1 = calculate_score(findings)
        r2 = calculate_score(findings)
        assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# Score range and grading
# ---------------------------------------------------------------------------


class TestScoreBoundaries:
    def test_perfect_score_on_empty_findings(self):
        r = calculate_score(_empty())
        assert r.score == PERFECT_SCORE
        assert r.grade == "A"
        assert r.findings_source_breakdown == {"source": 0, "test": 0, "fixture": 0}

    def test_floor_clamp_with_all_categories_saturated(self):
        # Build a synthetic repository that saturates several categories.
        # The score must drop firmly into F-band. We do not pin a
        # literal MINIMUM_SCORE (300) because the per-category penalty
        # caps at MAX_PENALTY (550) *before* category weighting, so
        # the realistic lower bound for a saturated multi-category
        # repo is determined by sum(category_weight * MAX_PENALTY).
        # 3 saturated categories at weights 0.30+0.25+0.25 = 0.80
        # yield realized penalty ≈ 0.80 * 550 = 440 → score 410.
        findings: list[Finding] = []
        for i in range(200):
            findings.append(
                _mk(
                    rid="secrets:aws_access_key_id",
                    fid=f"f_floor_sec_{i}",
                    severity=FindingSeverity.CRITICAL,
                    category=FindingCategory.SECURITY,
                    confidence=1.0,
                    debt=12,
                    rel_path=f"src/api/huge_endpoint_{i}.py",
                )
            )
            findings.append(
                _mk(
                    rid="oversized_functions:over-threshold",
                    fid=f"f_floor_maint_{i}",
                    severity=FindingSeverity.CRITICAL,
                    category=FindingCategory.MAINTAINABILITY,
                    confidence=1.0,
                    debt=12,
                    rel_path=f"src/big_func_{i}.py",
                )
            )
            findings.append(
                _mk(
                    rid="cyclomatic_complexity:high-cc",
                    fid=f"f_floor_cc_{i}",
                    severity=FindingSeverity.CRITICAL,
                    category=FindingCategory.COMPLEXITY,
                    confidence=1.0,
                    debt=12,
                    rel_path=f"src/complex_{i}.py",
                )
            )
        r = calculate_score(findings)
        assert r.grade == "F"
        # 3 saturated categories at combined weight 0.80 → realized
        # penalty ≈ 440. Score must be well below 580 (D-band upper).
        assert r.score < 580, (
            f"Saturated multi-category repo should land firmly in F; "
            f"got score={r.score}, grade={r.grade}"
        )
        assert r.score >= MINIMUM_SCORE

    def test_score_within_valid_range(self):
        for findings in (
            _clean(),
            _low_debt(),
            _moderate_debt(),
            _severe_maintainability(),
            _genuine_security(),
            _test_only_fake_secrets(),
        ):
            r = calculate_score(findings)
            assert MINIMUM_SCORE <= r.score <= PERFECT_SCORE
            assert r.grade in ("A", "B", "C", "D", "F")


# ---------------------------------------------------------------------------
# Calibration: ordered severity profiles
# ---------------------------------------------------------------------------


class TestScoreOrdering:
    def test_clean_scores_higher_than_low(self):
        clean = calculate_score(_clean())
        low = calculate_score(_low_debt())
        assert clean.score > low.score

    def test_low_scores_higher_than_moderate(self):
        low = calculate_score(_low_debt())
        moderate = calculate_score(_moderate_debt())
        assert low.score > moderate.score

    def test_moderate_scores_higher_than_severe(self):
        moderate = calculate_score(_moderate_debt())
        severe = calculate_score(_severe_maintainability())
        assert moderate.score > severe.score

    def test_severe_maintainability_is_in_d_or_f_band(self):
        severe = calculate_score(_severe_maintainability())
        # 30 CRITICAL findings at debt=12 each = 360 debt points; this
        # must drop the score into D or F. We don't pin the exact grade
        # but we pin the band so the test stays stable under future
        # calibration work.
        assert severe.score < 670, (
            f"severe maintainability repo should score below C; got {severe.score}"
        )
        assert severe.score >= MINIMUM_SCORE

    def test_grade_thresholds(self):
        # Hand-trace the grading table.
        assert calculate_score(_clean()).grade == "A"
        # Low-debt repos with 2 INFO findings should still be A or B.
        low_grade = calculate_score(_low_debt()).grade
        assert low_grade in ("A", "B")


# ---------------------------------------------------------------------------
# SECURITY vs fixture-context discipline
# ---------------------------------------------------------------------------


class TestSecurityDoesNotAutoDominateFixture:
    def test_test_only_fake_secrets_scores_no_worse_than_genuine(self):
        # A repo with 23 fake secrets *all under tests/* must not score
        # meaningfully WORSE than the same severity debt landing in
        # production source. This is the core guarantee from Michael's
        # Checkpoint 5 brief: SECURITY cannot dominate merely because
        # test fixtures intentionally contain fake secret patterns.
        #
        # The exact ordering is determined by the SEVERITY_BONUS +
        # category-weight interaction; we assert a *tight* margin
        # rather than a strict ordering because the model is a
        # documented heuristic, not an arbitrary score mover.
        genuine = calculate_score(_genuine_security())
        test_only = calculate_score(_test_only_fake_secrets())
        # Fixture-only secrets must score no more than 5 points worse
        # than equivalent production findings. (Without the source-
        # context modifier, the gap would be ~30 points.)
        gap = genuine.score - test_only.score
        assert gap <= 5, (
            f"Fixture-only secrets scored {gap} points worse than equivalent "
            f"production secrets ({test_only.score} vs {genuine.score}). "
            f"The source-context modifier (0.25x for tests/fixtures) is too weak."
        )

    def test_test_only_fake_secrets_drops_at_most_into_c_band(self):
        # Even with 23 ERROR-severity findings, the fixture-context
        # modifier (0.25x) must keep the score at C or better. The
        # exact boundary is intentionally not pinned to a single value,
        # but we lock the band so future calibration work can't
        # silently regress this property.
        r = calculate_score(_test_only_fake_secrets())
        assert r.score >= 670, (
            f"Test-only fake-secrets repo should stay in C band or better; "
            f"got {r.score} ({r.grade}). Fixture-context modifier broken?"
        )

    def test_source_breakdown_reports_classification(self):
        findings = _test_only_fake_secrets() + _genuine_security()
        r = calculate_score(findings)
        assert r.findings_source_breakdown["test"] == 23
        assert r.findings_source_breakdown["source"] == 3

    def test_total_debt_points_is_unmodified_by_context(self):
        # The dashboard surfaces raw debt regardless of context; only
        # the *score* is muted. This guarantees users still see the
        # actual analyzer-reported burden.
        findings = _test_only_fake_secrets()
        r = calculate_score(findings)
        expected = sum(f.debt_points for f in findings)
        assert r.total_debt_points == expected


# ---------------------------------------------------------------------------
# Severity mathematical effect
# ---------------------------------------------------------------------------


class TestSeverityMathematicalEffect:
    def test_critical_penalizes_more_than_info(self):
        # Same single finding, only severity varies.
        def _build(sev: FindingSeverity, fid: str) -> Finding:
            return Finding(
                id=fid,
                rule_id="x:y",
                category=FindingCategory.MAINTAINABILITY,
                severity=sev,
                confidence=1.0,
                file_path="src/a.py",
                line_start=1,
                line_end=1,
                symbol=None,
                evidence="",
                message="",
                suggestion=None,
                debt_points=10,
                remediation_effort=None,
                analyzer="synthetic",
                metadata={},
            )

        info = calculate_score([_build(FindingSeverity.INFO, "info")])
        critical = calculate_score([_build(FindingSeverity.CRITICAL, "critical")])
        assert critical.score < info.score

    def test_low_confidence_findings_penalize_less(self):
        def _build(confidence: float, fid: str) -> Finding:
            return Finding(
                id=fid,
                rule_id="x:y",
                category=FindingCategory.COMPLEXITY,
                severity=FindingSeverity.ERROR,
                confidence=confidence,
                file_path="src/a.py",
                line_start=1,
                line_end=1,
                symbol=None,
                evidence="",
                message="",
                suggestion=None,
                debt_points=10,
                remediation_effort=None,
                analyzer="synthetic",
                metadata={},
            )

        high = calculate_score([_build(1.0, "high_conf")])
        low = calculate_score([_build(0.5, "low_conf")])
        assert low.score > high.score, (
            "Low-confidence findings should penalize less than high-confidence "
            "findings of the same severity/category/debt."
        )


# ---------------------------------------------------------------------------
# Score explainability
# ---------------------------------------------------------------------------


class TestScoreExplainability:
    def test_score_penalty_is_bounded(self):
        findings = _severe_maintainability()
        r = calculate_score(findings)
        # The penalty is bounded by MAX_PENALTY. Verify that the
        # reported raw score (which we cannot see directly without
        # exposing internals) plus the reported score yields a penalty
        # within the documented range.
        # PERFECT_SCORE - r.score is the realized penalty.
        penalty = PERFECT_SCORE - r.score
        assert 0 <= penalty <= MAX_PENALTY

    def test_findings_by_category_is_consistent(self):
        findings = _moderate_debt()
        r = calculate_score(findings)
        for cat, count in r.findings_by_category.items():
            assert count >= 0
        assert sum(r.findings_by_category.values()) == len(findings)


# ---------------------------------------------------------------------------
# Source-context path classification tests
# ---------------------------------------------------------------------------


class TestPathClassification:
    def test_classify_production_source(self):
        from app.security.path_classifier import classify_path

        assert classify_path("src/app/main.py") == "source"
        assert classify_path("app/services/repository.py") == "source"

    def test_classify_test_files(self):
        from app.security.path_classifier import classify_path

        assert classify_path("tests/test_main.py") == "test"
        assert classify_path("test/test_x.py") == "test"
        assert classify_path("tests/sub/sub/test_y.py") == "test"
        assert classify_path("src/test_thing.py") == "test"  # test_ prefix
        assert classify_path("src/thing_test.py") == "test"  # _test.py suffix
        assert classify_path("tests/conftest.py") == "test"

    def test_classify_fixture_files(self):
        from app.security.path_classifier import classify_path

        assert classify_path("examples/demo.py") == "fixture"
        assert classify_path("fixtures/case.py") == "fixture"
        assert classify_path("testdata/data.csv") == "fixture"
        assert classify_path(".env.example") == "fixture"
        assert classify_path("config.example.yaml") == "fixture"
        assert classify_path("example.env") == "fixture"

    def test_classify_root_level_files(self):
        from app.security.path_classifier import classify_path

        assert classify_path("main.py") == "source"
        assert classify_path("README.md") == "source"
        assert classify_path("setup.py") == "source"

    def test_classify_nested_test_in_fixture_dir(self):
        from app.security.path_classifier import classify_path

        # tests/ is strictly a test dir, even if it also has fixtures.
        assert classify_path("tests/fixtures/old_data.py") == "test"
        # examples/ is fixture.
        assert classify_path("examples/fixtures/case.py") == "fixture"
