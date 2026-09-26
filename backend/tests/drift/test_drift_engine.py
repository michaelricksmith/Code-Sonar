"""Unit tests for ``app.drift.drift_engine``.

``test_invariants.py`` covers the Checkpoint 6 product scenarios against
``compute_drift``. This module covers the rest of the engine's public
surface: ``None`` baselines/currents, debt-only risk movement,
severity drill-downs, bucket debt deltas, the ``to_dict`` contracts,
and the classification constants.
"""

from __future__ import annotations

from app.drift.drift_engine import (
    ALL_CLASSIFICATIONS,
    IMPROVED,
    NEW,
    PERSISTENT,
    RESOLVED,
    WORSENED,
    _BucketCounts,
    _risk,
    compute_drift,
)
from app.history import SCHEMA_VERSION, FindingSnapshot, ScanRecord


def _mk_finding(
    *,
    fid: str,
    category: str = "maintainability",
    severity: str = "warning",
    debt: int = 4,
    analyzer: str = "test_analyzer",
) -> FindingSnapshot:
    return FindingSnapshot.from_dict({
        "id": fid,
        "rule_id": "test:rule",
        "category": category,
        "severity": severity,
        "confidence": 1.0,
        "file_path": "src/app.py",
        "line_start": 1,
        "line_end": 1,
        "symbol": None,
        "evidence": "",
        "message": f"finding {fid}",
        "suggestion": None,
        "debt_points": debt,
        "analyzer": analyzer,
        "metadata": {},
    })


def _mk_record(
    *,
    scan_id: str,
    score: int,
    grade: str,
    findings: list[FindingSnapshot],
) -> ScanRecord:
    return ScanRecord.from_dict({
        "scan_id": scan_id,
        "repository_id": "abc1234",
        "repository_path": "c:/example/repo",
        "scanned_at": "2026-08-22T17:00:00+00:00",
        "schema_version": SCHEMA_VERSION,
        "score": score,
        "grade": grade,
        "total_debt_points": sum(f.debt_points for f in findings),
        "finding_count": len(findings),
        "category_scores": {},
        "severity_distribution": {},
        "findings_by_category": {},
        "findings_source_breakdown": {"source": 0, "test": 0, "fixture": 0},
        "findings": [f.to_dict() for f in findings],
    })


class TestNoneSides:
    def test_none_baseline_and_none_current_counts(self):
        result = compute_drift(None, None)
        assert result.summary.new_count == 0
        assert result.summary.resolved_count == 0
        assert result.summary.persistent_count == 0
        assert result.summary.score_delta == 0
        assert result.summary.debt_delta == 0
        assert result.summary.finding_delta == 0

    def test_none_baseline_and_none_current_empty(self):
        result = compute_drift(None, None)
        assert result.findings == []
        assert result.by_category == {}
        assert result.by_analyzer == {}
        assert result.by_severity == {}

    def test_none_baseline_marks_everything_new(self):
        current = _mk_record(
            scan_id="s2",
            score=700,
            grade="C",
            findings=[_mk_finding(fid="f1"), _mk_finding(fid="f2", category="security")],
        )
        result = compute_drift(None, current)
        assert result.summary.new_count == 2
        assert result.summary.resolved_count == 0
        assert all(f.classification == NEW for f in result.findings)
        assert result.summary.score_delta == 700
        assert result.summary.baseline_scan_id == ""
        assert result.summary.current_scan_id == "s2"

    def test_none_current_marks_everything_resolved(self):
        baseline = _mk_record(
            scan_id="s1",
            score=700,
            grade="C",
            findings=[_mk_finding(fid="f1"), _mk_finding(fid="f2")],
        )
        result = compute_drift(baseline, None)
        assert result.summary.new_count == 0
        assert result.summary.resolved_count == 2
        assert all(f.classification == RESOLVED for f in result.findings)
        assert result.summary.score_delta == -700
        assert result.summary.baseline_scan_id == "s1"


class TestDebtOnlyMovement:
    def test_debt_increase_same_severity_is_worsened(self):
        baseline = _mk_record(
            scan_id="s1", score=750, grade="B",
            findings=[_mk_finding(fid="f1", severity="warning", debt=4)],
        )
        current = _mk_record(
            scan_id="s2", score=730, grade="C",
            findings=[_mk_finding(fid="f1", severity="warning", debt=8)],
        )
        result = compute_drift(baseline, current)
        assert result.summary.worsened_count == 1
        df = result.findings[0]
        assert df.classification == WORSENED
        # risk: 4*2=8 -> 8*2=16
        assert df.risk_delta == 8.0
        assert df.baseline_debt_points == 4
        assert df.current_debt_points == 8

    def test_debt_decrease_same_severity_is_improved(self):
        baseline = _mk_record(
            scan_id="s1", score=730, grade="C",
            findings=[_mk_finding(fid="f1", severity="error", debt=8)],
        )
        current = _mk_record(
            scan_id="s2", score=760, grade="B",
            findings=[_mk_finding(fid="f1", severity="error", debt=4)],
        )
        result = compute_drift(baseline, current)
        assert result.summary.improved_count == 1
        df = result.findings[0]
        assert df.classification == IMPROVED
        # risk: 8*3=24 -> 4*3=12
        assert df.risk_delta == -12.0


class TestSeverityDrilldown:
    def test_by_severity_counts(self):
        baseline = _mk_record(
            scan_id="s1", score=750, grade="B",
            findings=[
                _mk_finding(fid="w1", severity="warning"),
                _mk_finding(fid="e1", severity="error"),
            ],
        )
        current = _mk_record(
            scan_id="s2", score=720, grade="C",
            findings=[
                _mk_finding(fid="w1", severity="warning"),
                _mk_finding(fid="c1", severity="critical"),
            ],
        )
        result = compute_drift(baseline, current)
        assert result.by_severity["warning"].persistent == 1
        assert result.by_severity["error"].resolved == 1
        assert result.by_severity["critical"].new == 1
        assert result.summary.persistent_count == 1


class TestBucketDebtDeltas:
    def test_new_resolved_and_worsened_debt_deltas(self):
        baseline = _mk_record(
            scan_id="s1", score=750, grade="B",
            findings=[
                _mk_finding(fid="gone", category="security", debt=6),
                _mk_finding(fid="worse", category="security", severity="warning", debt=4),
            ],
        )
        current = _mk_record(
            scan_id="s2", score=720, grade="C",
            findings=[
                _mk_finding(fid="fresh", category="security", debt=10),
                _mk_finding(fid="worse", category="security", severity="warning", debt=8),
            ],
        )
        result = compute_drift(baseline, current)
        bucket = result.by_category["security"]
        assert bucket.new == 1
        assert bucket.resolved == 1
        assert bucket.worsened == 1
        # +10 (new) - 6 (resolved) + (8 - 4) (worsened)
        assert bucket.debt_delta == 8


class TestToDictContracts:
    def test_drift_finding_to_dict_for_new(self):
        current = _mk_record(
            scan_id="s2", score=700, grade="C", findings=[_mk_finding(fid="f1")]
        )
        result = compute_drift(None, current)
        data = result.findings[0].to_dict()
        assert data["finding_id"] == "f1"
        assert data["classification"] == NEW
        assert data["baseline_severity"] is None
        assert data["baseline_debt_points"] is None
        assert data["current_severity"] == "warning"
        assert data["current_debt_points"] == 4
        assert data["risk_delta"] == 0.0

    def test_drift_summary_to_dict_nests_scans(self):
        baseline = _mk_record(
            scan_id="s1", score=750, grade="B", findings=[_mk_finding(fid="f1")]
        )
        current = _mk_record(
            scan_id="s2", score=720, grade="C", findings=[_mk_finding(fid="f1")]
        )
        data = compute_drift(baseline, current).summary.to_dict()
        assert data["baseline"]["scan_id"] == "s1"
        assert data["baseline"]["score"] == 750
        assert data["current"]["scan_id"] == "s2"
        assert data["current"]["score"] == 720
        assert data["persistent_count"] == 1

    def test_drift_result_to_dict_structure(self):
        result = compute_drift(None, None)
        data = result.to_dict()
        assert set(data.keys()) == {
            "summary", "findings", "by_category", "by_analyzer", "by_severity"
        }
        assert data["findings"] == []

    def test_bucket_counts_as_dict_defaults(self):
        assert _BucketCounts().as_dict() == {
            "new": 0,
            "resolved": 0,
            "persistent": 0,
            "worsened": 0,
            "improved": 0,
            "score_delta": 0.0,
            "debt_delta": 0,
        }


class TestClassificationConstants:
    def test_all_classifications_tuple(self):
        assert ALL_CLASSIFICATIONS == (NEW, RESOLVED, PERSISTENT, WORSENED, IMPROVED)
        assert set(ALL_CLASSIFICATIONS) == {
            "new", "resolved", "persistent", "worsened", "improved"
        }


class TestRiskProxy:
    def test_unknown_severity_defaults_to_weight_one(self):
        snap = _mk_finding(fid="x", severity="blocker", debt=5)
        assert _risk(snap) == 5.0
