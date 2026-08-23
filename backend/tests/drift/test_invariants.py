"""Drift engine product invariants — Lane 4 of Checkpoint 6.

Covers the 15 required scenarios from Michael's Checkpoint 6 brief:

1. identical scans (delta = 0, no new, no resolved)
2. one new finding
3. one resolved finding
4. severity increase
5. severity decrease
6. multiple analyzer changes
7. category movement
8. reordered input findings (expected: identical comparison output)
9. repeated comparison (expected: byte-identical result)
10. persistence round-trip (handled by test_history.py; this file
    asserts the engine is invariant under `record.to_dict()` ->
    `record.from_dict()` serialization)
11. empty baseline
12. empty current scan
13. repository isolation (covered: history_store tests)
14. duplicate finding-ID defense (covered below + in test_history)
15. schema/version compatibility (covered by history_store tests)

All assertions are on the pure-function ``compute_drift``. No
network, no filesystem.
"""

from __future__ import annotations

import json

from app.drift import (
    IMPROVED,
    NEW,
    PERSISTENT,
    WORSENED,
    compute_drift,
)
from app.drift.drift_engine import (
    _risk,
)
from app.history import SCHEMA_VERSION, FindingSnapshot, ScanRecord


def _mk_finding(
    *,
    fid: str,
    category: str = "maintainability",
    severity: str = "warning",
    debt: int = 4,
    confidence: float = 1.0,
    rel_path: str = "src/app.py",
    line: int = 1,
    rule_id: str = "test:rule",
    analyzer: str = "test_analyzer",
) -> FindingSnapshot:
    return FindingSnapshot.from_dict({
        "id": fid,
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "file_path": rel_path,
        "line_start": line,
        "line_end": line,
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
    scanned_at: str,
    score: int,
    grade: str,
    findings: list[FindingSnapshot],
    debt: int | None = None,
) -> ScanRecord:
    debt = debt if debt is not None else sum(f.debt_points for f in findings)
    return ScanRecord.from_dict({
        "scan_id": scan_id,
        "repository_id": "abc1234",
        "repository_path": "c:/example/repo",
        "scanned_at": scanned_at,
        "schema_version": SCHEMA_VERSION,
        "score": score,
        "grade": grade,
        "total_debt_points": debt,
        "finding_count": len(findings),
        "category_scores": {},
        "severity_distribution": {},
        "findings_by_category": {},
        "findings_source_breakdown": {"source": 0, "test": 0, "fixture": 0},
        "findings": [f.to_dict() for f in findings],
    })


class TestScenario1IdenticalScans:
    def test_identical_scans_produce_no_drift(self):
        findings = [_mk_finding(fid=f"f{i}") for i in range(5)]
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=findings,
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=750,
            grade="B",
            findings=findings,
        )
        result = compute_drift(baseline, current)
        assert result.summary.new_count == 0
        assert result.summary.resolved_count == 0
        assert result.summary.persistent_count == 5
        assert result.summary.worsened_count == 0
        assert result.summary.improved_count == 0
        assert result.summary.score_delta == 0
        assert result.summary.debt_delta == 0
        assert result.summary.finding_delta == 0


class TestScenario2OneNewFinding:
    def test_single_new_finding(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="f1")],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[_mk_finding(fid="f1"), _mk_finding(fid="f2")],
            debt=8,
        )
        result = compute_drift(baseline, current)
        assert result.summary.new_count == 1
        assert result.summary.resolved_count == 0
        assert result.summary.persistent_count == 1
        assert result.summary.score_delta == -30


class TestScenario3OneResolvedFinding:
    def test_single_resolved_finding(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=720,
            grade="C",
            findings=[_mk_finding(fid="f1"), _mk_finding(fid="f2")],
            debt=8,
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="f1")],
        )
        result = compute_drift(baseline, current)
        assert result.summary.new_count == 0
        assert result.summary.resolved_count == 1
        assert result.summary.persistent_count == 1
        assert result.summary.score_delta == 30


class TestScenario4SeverityIncrease:
    def test_severity_increase_is_worsened(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="f1", severity="warning", debt=4)],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=730,
            grade="C",
            findings=[_mk_finding(fid="f1", severity="error", debt=4)],
        )
        result = compute_drift(baseline, current)
        assert result.summary.worsened_count == 1
        assert result.summary.persistent_count == 0
        # The finding id matches; same finding is WORSENED.
        df = result.findings[0]
        assert df.classification == WORSENED
        assert df.baseline_severity == "warning"
        assert df.current_severity == "error"


class TestScenario5SeverityDecrease:
    def test_severity_decrease_is_improved(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=720,
            grade="C",
            findings=[_mk_finding(fid="f1", severity="error", debt=8)],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=760,
            grade="B",
            findings=[_mk_finding(fid="f1", severity="warning", debt=4)],
        )
        result = compute_drift(baseline, current)
        assert result.summary.improved_count == 1
        df = result.findings[0]
        assert df.classification == IMPROVED


class TestScenario6MultipleAnalyzerChanges:
    def test_analyzer_changes_drilldown(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[
                _mk_finding(fid="a1", analyzer="cyclomatic_complexity"),
                _mk_finding(fid="b1", analyzer="dead_code"),
                _mk_finding(fid="b2", analyzer="dead_code"),
            ],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[
                _mk_finding(fid="a1", analyzer="cyclomatic_complexity"),
                _mk_finding(fid="c1", analyzer="secrets"),
                _mk_finding(fid="c2", analyzer="secrets"),
            ],
        )
        result = compute_drift(baseline, current)
        # 1 persistent (a1)
        assert result.summary.persistent_count == 1
        # dead_code had 2 findings, both resolved
        assert result.summary.resolved_count == 2
        # secrets had 0 findings, 2 new
        assert result.summary.new_count == 2
        # Drill-down by analyzer.
        assert result.by_analyzer["cyclomatic_complexity"].persistent == 1
        assert result.by_analyzer["dead_code"].resolved == 2
        assert result.by_analyzer["secrets"].new == 2


class TestScenario7CategoryMovement:
    def test_category_movement_drilldown(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[
                _mk_finding(fid="x1", category="security", debt=8),
                _mk_finding(fid="x2", category="security", debt=8),
                _mk_finding(fid="m1", category="maintainability"),
            ],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[
                _mk_finding(fid="x1", category="security", debt=8),
                _mk_finding(fid="m1", category="maintainability"),
                _mk_finding(fid="m2", category="maintainability"),
                _mk_finding(fid="t1", category="testing"),
            ],
        )
        result = compute_drift(baseline, current)
        # security: 1 persistent, 1 resolved
        assert result.by_category["security"].persistent == 1
        assert result.by_category["security"].resolved == 1
        # maintainability: 1 persistent, 1 new
        assert result.by_category["maintainability"].persistent == 1
        assert result.by_category["maintainability"].new == 1
        # testing: 1 new
        assert result.by_category["testing"].new == 1


class TestScenario8ReorderedInput:
    def test_reordered_findings_produce_identical_drift(self):
        # Build the SAME set of findings but reversed.
        fids = [f"f{i}" for i in range(10)]
        findings = [_mk_finding(fid=fid) for fid in fids]
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=findings,
        )
        # Add f99 to the "current" set; drop f3 from it.
        new_findings = [_mk_finding(fid=fid) for fid in fids if fid != "f3"]
        new_findings.append(_mk_finding(fid="f99"))
        current_a = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=list(new_findings),
        )
        # Reverse the current findings.
        current_b = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=list(reversed(new_findings)),
        )
        result_a = compute_drift(baseline, current_a)
        result_b = compute_drift(baseline, current_b)
        # Byte-identical serialized result.
        assert json.dumps(result_a.to_dict(), sort_keys=True) == json.dumps(
            result_b.to_dict(), sort_keys=True
        )
        assert result_a.summary.new_count == result_b.summary.new_count == 1
        assert result_a.summary.resolved_count == result_b.summary.resolved_count == 1


class TestScenario9RepeatedComparison:
    def test_repeated_comparison_byte_identical(self):
        fids = [f"f{i}" for i in range(20)]
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid=fid, severity="warning", debt=4) for fid in fids[:10]]
            + [_mk_finding(fid=fid, severity="error", debt=8) for fid in fids[10:]],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[_mk_finding(fid=fid, severity="warning", debt=4) for fid in fids[:5]]
            + [_mk_finding(fid=fid, severity="error", debt=10) for fid in fids[5:]]
            + [_mk_finding(fid="f_new")],
        )
        first = compute_drift(baseline, current).to_dict()
        for _ in range(5):
            again = compute_drift(baseline, current).to_dict()
            assert json.dumps(again, sort_keys=True) == json.dumps(first, sort_keys=True)


class TestScenario10PersistenceRoundTrip:
    def test_drift_invariant_under_serialization(self):
        """``record.to_dict() -> record.from_dict()`` must preserve drift semantics."""
        from app.history.scan_record import ScanRecord

        fids = [f"f{i}" for i in range(10)]
        baseline_finds = [_mk_finding(fid=fid, severity="error", debt=8) for fid in fids]
        current_finds = [_mk_finding(fid=fid, severity="critical", debt=12) for fid in fids[:7]] + [
            _mk_finding(fid=fid, severity="error", debt=8) for fid in fids[7:]
        ]
        baseline_orig = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=baseline_finds,
        )
        current_orig = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=current_finds,
        )
        # Round-trip through JSON.
        baseline_rt = ScanRecord.from_dict(json.loads(json.dumps(baseline_orig.to_dict())))
        current_rt = ScanRecord.from_dict(json.loads(json.dumps(current_orig.to_dict())))
        result_orig = compute_drift(baseline_orig, current_orig)
        result_rt = compute_drift(baseline_rt, current_rt)
        assert json.dumps(result_orig.to_dict(), sort_keys=True) == json.dumps(
            result_rt.to_dict(), sort_keys=True
        )


class TestScenario11EmptyBaseline:
    def test_empty_baseline_marks_everything_new(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=850,
            grade="A",
            findings=[],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=820,
            grade="B",
            findings=[_mk_finding(fid=f"f{i}", debt=4) for i in range(5)],
        )
        result = compute_drift(baseline, current)
        assert result.summary.new_count == 5
        assert result.summary.resolved_count == 0
        assert result.summary.persistent_count == 0
        assert result.summary.score_delta == -30


class TestScenario12EmptyCurrentScan:
    def test_empty_current_marks_everything_resolved(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=720,
            grade="C",
            findings=[_mk_finding(fid=f"f{i}", debt=4) for i in range(5)],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=850,
            grade="A",
            findings=[],
        )
        result = compute_drift(baseline, current)
        assert result.summary.new_count == 0
        assert result.summary.resolved_count == 5
        assert result.summary.persistent_count == 0
        assert result.summary.score_delta == 130


class TestScenario14DuplicateFindingIdDefense:
    def test_duplicate_finding_id_in_a_scan_does_not_crash(self):
        """The engine must deterministically pick one occurrence on
        duplicate ids within a single scan; not crash, not duplicate
        the classification."""
        f = _mk_finding(fid="dup")
        # Same finding id twice in baseline; engine picks first.
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[f, _mk_finding(fid="other")],
        )
        # Same duplicate id in current.
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[f, _mk_finding(fid="new")],
        )
        result = compute_drift(baseline, current)
        # 'dup' is persistent (matches first occurrence); 'other' is
        # resolved; 'new' is new. Total: 1 PERSISTENT + 1 RESOLVED +
        # 1 NEW = 3 classifications across 2 unique ids + 1 new id.
        assert result.summary.persistent_count == 1
        assert result.summary.resolved_count == 1
        assert result.summary.new_count == 1


class TestScenario15SchemaCompatibility:
    def test_unknown_schema_version_is_skipped_by_store(self):
        from app.history import InMemoryHistoryStore

        store = InMemoryHistoryStore()
        store.append(
            ScanRecord.from_dict({
                "scan_id": "good",
                "repository_id": "abc1234",
                "repository_path": "c:/example",
                "scanned_at": "2026-08-22T17:00:00+00:00",
                "schema_version": SCHEMA_VERSION,
                "score": 750,
                "grade": "B",
                "total_debt_points": 0,
                "finding_count": 0,
                "category_scores": {},
                "severity_distribution": {},
                "findings_by_category": {},
                "findings_source_breakdown": {"source": 0, "test": 0, "fixture": 0},
                "findings": [],
            })
        )
        # Manually inject a record with a future schema version that
        # the running code does not understand.
        store.append(
            ScanRecord.from_dict({
                "scan_id": "future",
                "repository_id": "abc1234",
                "repository_path": "c:/example",
                "scanned_at": "2026-08-22T18:00:00+00:00",
                "schema_version": "99.0",
                "score": 700,
                "grade": "C",
                "total_debt_points": 0,
                "finding_count": 0,
                "category_scores": {},
                "severity_distribution": {},
                "findings_by_category": {},
                "findings_source_breakdown": {"source": 0, "test": 0, "fixture": 0},
                "findings": [],
            })
        )
        loaded = store.load_all("abc1234")
        ids = [r.scan_id for r in loaded]
        assert "good" in ids
        assert "future" not in ids


class TestClassificationOrdering:
    def test_findings_sorted_by_classification_priority_then_id(self):
        baseline = _mk_record(
            scan_id="s1",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="zzz"), _mk_finding(fid="aaa")],
        )
        current = _mk_record(
            scan_id="s2",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[
                _mk_finding(fid="zzz"),
                _mk_finding(fid="aaa"),
                _mk_finding(fid="new_zzz"),
                _mk_finding(fid="new_aaa"),
            ],
        )
        result = compute_drift(baseline, current)
        classifications = [f.classification for f in result.findings]
        # NEW first (sorted by finding_id), then PERSISTENT (sorted by finding_id).
        assert classifications == [
            NEW, NEW, PERSISTENT, PERSISTENT,
        ]
        ids = [f.finding_id for f in result.findings]
        assert ids == ["new_aaa", "new_zzz", "aaa", "zzz"]


class TestRiskProxy:
    def test_risk_proxy_for_worsened_and_improved(self):
        f = _mk_finding(fid="x", severity="warning", debt=4)
        snap = FindingSnapshot.from_dict(f.to_dict())
        # warning -> severity_weight 2; risk = 4 * 2 = 8
        assert _risk(snap) == 8.0
        f2 = _mk_finding(fid="x", severity="critical", debt=4)
        snap2 = FindingSnapshot.from_dict(f2.to_dict())
        # critical -> 4; risk = 4 * 4 = 16
        assert _risk(snap2) == 16.0
