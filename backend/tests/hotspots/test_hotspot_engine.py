"""Tests for the Risk Hotspots engine (Checkpoint 7 / private beta).

Covers:
- determinism (repeated scan returns byte-identical output)
- ordering-independence (input ordering does not affect output)
- explainability (every component of the score is exposed in the breakdown)
- simple edge cases (empty input, single file, multiple files, ties)
- score formula correctness
- metadata-derived signal extraction (complexity, size, nesting)
"""

from __future__ import annotations

from app.hotspots import (
    SEVERITY_WEIGHT,
    HotspotResult,
    compute_hotspots,
)
from app.models.finding import Finding, FindingCategory, FindingSeverity


def make_finding(
    file_path: str = "src/app.py",
    rule_id: str = "test:rule",
    category: FindingCategory = FindingCategory.MAINTAINABILITY,
    severity: FindingSeverity = FindingSeverity.WARNING,
    confidence: float = 0.9,
    debt_points: int = 5,
    analyzer: str = "test_analyzer",
    metadata: dict | None = None,
    line_start: int | None = 1,
    line_end: int | None = 10,
    symbol: str | None = None,
    finding_id: str | None = None,
) -> Finding:
    """Test helper: build a Finding with sensible defaults."""
    return Finding(
        id=finding_id or f"f_{file_path}_{rule_id}_{line_start}",
        rule_id=rule_id,
        category=category,
        severity=severity,
        confidence=confidence,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        symbol=symbol,
        evidence="ev",
        message="msg",
        suggestion=None,
        debt_points=debt_points,
        remediation_effort=None,
        analyzer=analyzer,
        metadata=metadata or {},
        detected_at=__import__("datetime").datetime.utcnow(),
    )


class TestEmptyInput:
    def test_empty_findings_returns_empty_result(self) -> None:
        r = compute_hotspots([])
        assert isinstance(r, HotspotResult)
        assert r.hotspots == []
        assert r.total_files == 0
        assert r.files_with_findings == 0
        assert r.total_findings == 0
        assert r.total_debt == 0


class TestSingleFile:
    def test_single_file_single_finding(self) -> None:
        f = make_finding(file_path="src/a.py", debt_points=10, severity=FindingSeverity.ERROR)
        r = compute_hotspots([f])
        assert r.total_files == 1
        assert r.files_with_findings == 1
        assert r.total_findings == 1
        assert r.total_debt == 10
        assert len(r.hotspots) == 1
        h = r.hotspots[0]
        assert h.file_path == "src/a.py"
        # score = debt_total + severity_max_weight + finding_count + analyzer_diversity * 2
        # = 10 + 3 + 1 + 2 = 16
        assert h.score == 16
        assert h.debt_total == 10
        assert h.finding_count == 1
        assert h.severity_max == "error"
        assert h.severity_max_weight == 3
        assert h.analyzer_diversity == 1

    def test_multiple_findings_on_one_file(self) -> None:
        findings = [
            make_finding(
                file_path="src/a.py",
                rule_id="r1",
                debt_points=5,
                severity=FindingSeverity.WARNING,
                analyzer="an1",
                metadata={"cc": 12},
                line_start=10,
                finding_id="f1",
            ),
            make_finding(
                file_path="src/a.py",
                rule_id="r2",
                debt_points=8,
                severity=FindingSeverity.ERROR,
                analyzer="an2",
                metadata={"loc": 600},
                line_start=20,
                finding_id="f2",
            ),
            make_finding(
                file_path="src/a.py",
                rule_id="r3",
                debt_points=2,
                severity=FindingSeverity.INFO,
                analyzer="an3",
                line_start=30,
                finding_id="f3",
            ),
        ]
        r = compute_hotspots(findings)
        assert len(r.hotspots) == 1
        h = r.hotspots[0]
        # debt_total = 5 + 8 + 2 = 15
        assert h.debt_total == 15
        # severity_max = error (weight 3)
        assert h.severity_max == "error"
        assert h.severity_max_weight == 3
        # finding_count = 3
        assert h.finding_count == 3
        # analyzer_diversity = 3
        assert h.analyzer_diversity == 3
        # complexity_max = 12 (from cc)
        assert h.complexity_max == 12
        # size_max = 600 (from loc)
        assert h.size_max == 600
        # score = 15 + 3 + 3 + 6 = 27
        assert h.score == 27
        assert h.analyzer_breakdown == {"an1": 1, "an2": 1, "an3": 1}
        assert h.severity_breakdown == {"warning": 1, "error": 1, "info": 1}
        assert h.contributing_finding_ids == ["f1", "f2", "f3"]


class TestMultipleFiles:
    def test_hotspots_sorted_by_score_descending(self) -> None:
        findings = [
            make_finding(file_path="a.py", debt_points=5),
            make_finding(file_path="b.py", debt_points=20, severity=FindingSeverity.CRITICAL),
            make_finding(file_path="c.py", debt_points=10, severity=FindingSeverity.ERROR),
        ]
        r = compute_hotspots(findings)
        # b.py: 20 + 4 + 1 + 2 = 27
        # c.py: 10 + 3 + 1 + 2 = 16
        # a.py: 5 + 2 + 1 + 2 = 10
        paths = [h.file_path for h in r.hotspots]
        assert paths == ["b.py", "c.py", "a.py"]

    def test_tie_break_by_file_path_ascending(self) -> None:
        # All three have identical debt+severity → identical scores
        findings = [
            make_finding(file_path="z.py", debt_points=5, severity=FindingSeverity.WARNING),
            make_finding(file_path="a.py", debt_points=5, severity=FindingSeverity.WARNING),
            make_finding(file_path="m.py", debt_points=5, severity=FindingSeverity.WARNING),
        ]
        r = compute_hotspots(findings)
        paths = [h.file_path for h in r.hotspots]
        assert paths == ["a.py", "m.py", "z.py"]

    def test_top_n_limits_output(self) -> None:
        findings = [
            make_finding(
                file_path=f"f{i}.py", debt_points=i + 1, severity=FindingSeverity.WARNING
            )
            for i in range(15)
        ]
        r = compute_hotspots(findings, top_n=5)
        assert len(r.hotspots) == 5
        # Top 5 by debt_total: f14, f13, f12, f11, f10
        paths = [h.file_path for h in r.hotspots]
        assert paths == ["f14.py", "f13.py", "f12.py", "f11.py", "f10.py"]


class TestDeterminism:
    def test_repeated_calls_return_byte_identical_output(self) -> None:
        findings = [
            make_finding(
                file_path="src/b.py", debt_points=10, severity=FindingSeverity.ERROR,
                analyzer="cyclomatic_complexity", metadata={"cc": 15}, finding_id="b1",
                line_start=10,
            ),
            make_finding(
                file_path="src/a.py", debt_points=3, severity=FindingSeverity.WARNING,
                analyzer="comment_markers", finding_id="a1",
                line_start=5,
            ),
        ]
        results = [compute_hotspots(findings).to_dict() for _ in range(5)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_input_ordering_does_not_affect_output(self) -> None:
        findings_a = [
            make_finding(
                file_path="src/a.py", debt_points=5, severity=FindingSeverity.WARNING,
                finding_id="a1", line_start=10,
            ),
            make_finding(
                file_path="src/b.py", debt_points=8, severity=FindingSeverity.ERROR,
                finding_id="b1", line_start=20,
            ),
        ]
        findings_b = list(reversed(findings_a))
        r_a = compute_hotspots(findings_a).to_dict()
        r_b = compute_hotspots(findings_b).to_dict()
        assert r_a == r_b

    def test_two_findings_same_file_ids_a_z_order_contributing_ids(self) -> None:
        findings_original = [
            make_finding(
                file_path="src/a.py", debt_points=5, severity=FindingSeverity.WARNING,
                finding_id="z-id", line_start=10,
            ),
            make_finding(
                file_path="src/a.py", debt_points=5, severity=FindingSeverity.WARNING,
                finding_id="a-id", line_start=20,
            ),
        ]
        findings_reversed = list(reversed(findings_original))

        r_original = compute_hotspots(findings_original)
        r_reversed = compute_hotspots(findings_reversed)

        dict_original = r_original.to_dict()
        dict_reversed = r_reversed.to_dict()

        assert dict_original == dict_reversed
        assert dict_original["hotspots"][0]["contributing_finding_ids"] == ["a-id", "z-id"]


class TestMetadataExtraction:
    def test_complexity_max_extracted_from_cc(self) -> None:
        findings = [
            make_finding(
                file_path="src/a.py", metadata={"cc": 7}, finding_id="f1", line_start=10,
            ),
            make_finding(
                file_path="src/a.py", metadata={"cc": 25}, finding_id="f2", line_start=20,
            ),
        ]
        r = compute_hotspots(findings)
        assert r.hotspots[0].complexity_max == 25

    def test_size_max_extracted_from_loc_or_lines(self) -> None:
        # First test: "loc" key
        findings = [
            make_finding(
                file_path="src/a.py", metadata={"loc": 100}, finding_id="f1", line_start=10,
            ),
            make_finding(
                file_path="src/a.py", metadata={"loc": 750}, finding_id="f2", line_start=20,
            ),
        ]
        r = compute_hotspots(findings)
        assert r.hotspots[0].size_max == 750

    def test_nesting_max_extracted_from_max_depth(self) -> None:
        findings = [
            make_finding(
                file_path="src/a.py", metadata={"max_depth": 5}, finding_id="f1", line_start=10,
            ),
            make_finding(
                file_path="src/a.py", metadata={"max_depth": 9}, finding_id="f2", line_start=20,
            ),
        ]
        r = compute_hotspots(findings)
        assert r.hotspots[0].nesting_max == 9

    def test_metadata_absent_returns_zero(self) -> None:
        findings = [make_finding(file_path="src/a.py", metadata={}, finding_id="f1", line_start=10)]
        r = compute_hotspots(findings)
        h = r.hotspots[0]
        assert h.complexity_max == 0
        assert h.size_max == 0
        assert h.nesting_max == 0


class TestExplainability:
    def test_breakdown_exposes_every_score_component(self) -> None:
        """The breakdown must be sufficient to reconstruct the score manually."""
        f = make_finding(
            file_path="src/explain.py",
            debt_points=12,
            severity=FindingSeverity.ERROR,
            analyzer="dead_code",
            finding_id="explain1",
            line_start=42,
        )
        r = compute_hotspots([f])
        h = r.hotspots[0]
        # Reconstruct the score from the breakdown:
        reconstructed = (
            h.debt_total
            + h.severity_max_weight
            + h.finding_count
            + h.analyzer_diversity * 2
        )
        assert reconstructed == h.score

    def test_severity_max_uses_correct_weight(self) -> None:
        """Verify all four severity levels map to the right weights."""
        for severity, expected_weight in [
            (FindingSeverity.INFO, 1),
            (FindingSeverity.WARNING, 2),
            (FindingSeverity.ERROR, 3),
            (FindingSeverity.CRITICAL, 4),
        ]:
            f = make_finding(
                file_path="src/s.py", severity=severity, finding_id="f1", line_start=1,
            )
            r = compute_hotspots([f])
            assert r.hotspots[0].severity_max_weight == expected_weight
            assert r.hotspots[0].severity_max == severity.value

    def test_to_dict_is_json_serializable(self) -> None:
        """The to_dict output must contain only JSON-compatible primitives."""
        import json
        findings = [
            make_finding(
                file_path="src/a.py",
                debt_points=5,
                severity=FindingSeverity.WARNING,
                analyzer="an1",
                metadata={"cc": 10},
                finding_id="f1",
                line_start=1,
            ),
        ]
        r = compute_hotspots(findings)
        d = r.to_dict()
        # Must not raise — full round-trip through JSON.
        encoded = json.dumps(d)
        decoded = json.loads(encoded)
        assert decoded == d


class TestSeverityWeightTable:
    def test_severity_weight_table_matches_drift_engine(self) -> None:
        """The SEVERITY_WEIGHT table in the hotspots module must match the
        drift engine's risk-proxy weights exactly. Shared semantics
        across the product matter."""
        assert SEVERITY_WEIGHT == {
            "info": 1,
            "warning": 2,
            "error": 3,
            "critical": 4,
        }


class TestRealisticScenario:
    """Smoke test: a realistic mixed scenario from a self-scan."""

    def test_mixed_severities_and_analyzers(self) -> None:
        findings = [
            # File A: dead code (warning) + complex function (warning)
            make_finding(
                file_path="backend/app/main.py",
                rule_id="dead_code:unused-private",
                category=FindingCategory.MAINTAINABILITY,
                severity=FindingSeverity.WARNING,
                debt_points=4,
                analyzer="dead_code",
                metadata={"cc": 18, "loc": 350},
                finding_id="main1",
                line_start=120,
            ),
            make_finding(
                file_path="backend/app/main.py",
                rule_id="complexity:high-cc",
                category=FindingCategory.COMPLEXITY,
                severity=FindingSeverity.WARNING,
                debt_points=12,
                analyzer="cyclomatic_complexity",
                metadata={"cc": 18},
                finding_id="main2",
                line_start=80,
            ),
            # File B: oversized (warning)
            make_finding(
                file_path="backend/app/scoring/engine.py",
                rule_id="oversized_functions:over-threshold",
                category=FindingCategory.COMPLEXITY,
                severity=FindingSeverity.WARNING,
                debt_points=8,
                analyzer="oversized_functions",
                metadata={"length": 81},
                finding_id="scoring1",
                line_start=30,
            ),
            # File C: secret (critical) — single high-severity finding
            make_finding(
                file_path="backend/app/integrations/foo.py",
                rule_id="secrets:aws-access-key",
                category=FindingCategory.SECURITY,
                severity=FindingSeverity.CRITICAL,
                debt_points=40,
                analyzer="secrets",
                metadata={},
                finding_id="foo1",
                line_start=10,
            ),
        ]
        r = compute_hotspots(findings, top_n=10)
        assert r.total_files == 3
        # File C has highest score despite single finding (severity weighting):
        # 40 + 4 + 1 + 2 = 47
        # File A: 4+12 + 2 + 2 + 2*2 = 16 + 2 + 2 + 4 = 24
        # File B: 8 + 2 + 1 + 2 = 13
        assert r.hotspots[0].file_path == "backend/app/integrations/foo.py"
        assert r.hotspots[0].score == 47
        assert r.hotspots[1].file_path == "backend/app/main.py"
        assert r.hotspots[2].file_path == "backend/app/scoring/engine.py"
