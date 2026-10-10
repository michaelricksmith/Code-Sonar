"""Unit tests for ``app.history.scan_record`` data classes.

Covers the gaps left by ``tests/history/test_history.py`` (which tests
store persistence, schema rejection, and repository isolation) and by
``tests/drift/test_drift_engine.py`` (which uses snapshots only as drift
fixtures): the ``FindingSnapshot`` constructor from live ``Finding``
objects, evidence redaction on the way in and out of the snapshot,
``matches_id``, the ``risk`` severity weights, ``ScanRecord`` direct
construction with copy isolation, legacy-record defaults in
``ScanRecord.from_dict``, and the ``build_scan_record`` defaults
(auto uuid scan id, iso timestamp, tenant binding, slug/branch
passthrough).
"""

from __future__ import annotations

from app.history import (
    SCHEMA_VERSION,
    FindingSnapshot,
    ScanRecord,
    build_scan_record,
)
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingSeverity,
)
from app.scoring.engine import SCORING_VERSION, ScoringResult
from app.security.tenant import LOCAL_TENANT_ID, bind_tenant, current_tenant_id

# 24+ alphanumeric chars so ``redact_secrets`` treats it as a secret.
_RAW_TOKEN = "sk_live_abcdefghijklmnop1234"

_LEGACY_TS = "2026-08-22T17:00:00+00:00"


def _mk_finding(
    *,
    fid: str = "f1",
    severity: FindingSeverity = FindingSeverity.WARNING,
    category: FindingCategory = FindingCategory.MAINTAINABILITY,
    evidence: str = "CC=28",
    debt_points: int = 4,
) -> Finding:
    return Finding(
        id=fid,
        rule_id="complexity:high-cc",
        category=category,
        severity=severity,
        confidence=0.9,
        file_path="src/app.py",
        line_start=10,
        line_end=20,
        symbol="main",
        evidence=evidence,
        message="function is complex",
        suggestion="split it",
        debt_points=debt_points,
        analyzer="complexity",
        metadata={"cc": 28},
    )


def _mk_snapshot_dict(**overrides) -> dict:
    data = {
        "id": "f1",
        "rule_id": "test:rule",
        "category": "maintainability",
        "severity": "warning",
        "confidence": 1.0,
        "file_path": "src/app.py",
        "line_start": 1,
        "line_end": 2,
        "symbol": "main",
        "evidence": "",
        "message": "a finding",
        "suggestion": "fix it",
        "debt_points": 4,
        "analyzer": "test_analyzer",
        "metadata": {"k": "v"},
    }
    data.update(overrides)
    return data


def _mk_record_dict(**overrides) -> dict:
    data = {
        "scan_id": "scan-1",
        "tenant_id": "local",
        "repository_id": "abc1234",
        "repository_path": "/repos/demo",
        "repository_slug": "owner/demo",
        "branch": "main",
        "scanned_at": _LEGACY_TS,
        "schema_version": SCHEMA_VERSION,
        "scoring_version": SCORING_VERSION,
        "score": 750,
        "grade": "B",
        "total_debt_points": 4,
        "finding_count": 1,
        "category_scores": {"maintainability": 750},
        "severity_distribution": {"warning": 1},
        "findings_by_category": {"maintainability": 1},
        "findings_source_breakdown": {"source": 1},
        "findings": [_mk_snapshot_dict()],
    }
    data.update(overrides)
    return data


def _mk_scoring(*, finding_count: int = 0, debt: int = 0) -> ScoringResult:
    return ScoringResult(
        score=800,
        grade="A",
        total_debt_points=debt,
        finding_count=finding_count,
        category_scores={"maintainability": 800},
        severity_distribution={"warning": finding_count},
        findings_by_category={"maintainability": finding_count},
        findings_source_breakdown={"source": finding_count},
        penalty_explanation={},
    )


class TestSchemaVersion:
    def test_schema_version_is_expected_string(self):
        assert SCHEMA_VERSION == "1.0"


class TestFindingSnapshotInit:
    def test_fields_mirror_live_finding(self):
        snap = FindingSnapshot(_mk_finding())
        assert snap.id == "f1"
        assert snap.rule_id == "complexity:high-cc"
        assert snap.category == "maintainability"
        assert snap.severity == "warning"
        assert snap.confidence == 0.9
        assert snap.file_path == "src/app.py"
        assert snap.symbol == "main"
        assert snap.analyzer == "complexity"

    def test_optional_none_fields_stay_none(self):
        f = _mk_finding()
        f.line_start = None
        f.line_end = None
        f.symbol = None
        f.suggestion = None
        snap = FindingSnapshot(f)
        assert snap.line_start is None
        assert snap.line_end is None
        assert snap.symbol is None
        assert snap.suggestion is None

    def test_evidence_redacted_on_init(self):
        snap = FindingSnapshot(_mk_finding(evidence=f"token {_RAW_TOKEN}"))
        assert _RAW_TOKEN not in snap.evidence
        assert "[REDACTED]" in snap.evidence

    def test_metadata_is_copied_on_init(self):
        f = _mk_finding()
        snap = FindingSnapshot(f)
        f.metadata["cc"] = 999
        assert snap.metadata == {"cc": 28}


class TestFindingSnapshotToDict:
    def test_evidence_redacted_on_way_out(self):
        snap = FindingSnapshot.from_dict(
            _mk_snapshot_dict(evidence=f"leaked {_RAW_TOKEN}")
        )
        d = snap.to_dict()
        assert _RAW_TOKEN not in d["evidence"]
        assert "[REDACTED]" in d["evidence"]

    def test_to_dict_round_trip_preserves_fields(self):
        snap = FindingSnapshot(_mk_finding())
        d = snap.to_dict()
        back = FindingSnapshot.from_dict(d)
        assert back.id == snap.id
        assert back.category == snap.category
        assert back.severity == snap.severity
        assert back.debt_points == snap.debt_points
        assert back.metadata == snap.metadata
        assert back.analyzer == snap.analyzer
        assert back.message == snap.message

    def test_to_dict_metadata_is_independent_copy(self):
        snap = FindingSnapshot.from_dict(_mk_snapshot_dict())
        d = snap.to_dict()
        d["metadata"]["k"] = "mutated"
        assert snap.metadata == {"k": "v"}


class TestFindingSnapshotFromDictEdgeCases:
    def test_missing_optional_keys_get_defaults(self):
        data = _mk_snapshot_dict()
        del data["line_start"]
        del data["line_end"]
        del data["symbol"]
        del data["suggestion"]
        del data["evidence"]
        del data["message"]
        snap = FindingSnapshot.from_dict(data)
        assert snap.line_start is None
        assert snap.line_end is None
        assert snap.symbol is None
        assert snap.suggestion is None
        assert snap.evidence == ""
        assert snap.message == ""

    def test_none_metadata_becomes_empty_dict(self):
        snap = FindingSnapshot.from_dict(_mk_snapshot_dict(metadata=None))
        assert snap.metadata == {}

    def test_numeric_strings_coerced(self):
        snap = FindingSnapshot.from_dict(
            _mk_snapshot_dict(confidence=1, debt_points="4")
        )
        assert snap.confidence == 1.0
        assert isinstance(snap.debt_points, int)
        assert snap.debt_points == 4


class TestMatchesId:
    def test_match_true(self):
        snap = FindingSnapshot.from_dict(_mk_snapshot_dict(id="abc"))
        assert snap.matches_id("abc")

    def test_match_false(self):
        snap = FindingSnapshot.from_dict(_mk_snapshot_dict(id="abc"))
        assert not snap.matches_id("xyz")


class TestRisk:
    def test_severity_weights(self):
        base = _mk_snapshot_dict(debt_points=10)
        info = FindingSnapshot.from_dict({**base, "severity": "info"})
        warning = FindingSnapshot.from_dict({**base, "severity": "warning"})
        error = FindingSnapshot.from_dict({**base, "severity": "error"})
        critical = FindingSnapshot.from_dict({**base, "severity": "critical"})
        assert info.risk == 10.0
        assert warning.risk == 20.0
        assert error.risk == 30.0
        assert critical.risk == 40.0

    def test_unknown_severity_defaults_to_one(self):
        snap = FindingSnapshot.from_dict(
            _mk_snapshot_dict(severity="blocker", debt_points=7)
        )
        assert snap.risk == 7.0

    def test_zero_debt_points_is_zero_risk(self):
        snap = FindingSnapshot.from_dict(
            _mk_snapshot_dict(severity="critical", debt_points=0)
        )
        assert snap.risk == 0.0


class TestScanRecordInit:
    def test_dict_inputs_are_copied(self):
        cat = {"maintainability": 750}
        record = ScanRecord.from_dict(
            _mk_record_dict(category_scores=cat)
        )
        cat["maintainability"] = 1
        assert record.category_scores == {"maintainability": 750}

    def test_direct_construction_defaults(self):
        record = ScanRecord(
            scan_id="s9",
            repository_id="r1",
            repository_path="/p",
            scanned_at=_LEGACY_TS,
            schema_version=SCHEMA_VERSION,
            score=900,
            grade="A",
            total_debt_points=0,
            finding_count=0,
            category_scores={},
            severity_distribution={},
            findings_by_category={},
            findings_source_breakdown={},
            findings=[],
        )
        assert record.tenant_id == LOCAL_TENANT_ID
        assert record.scoring_version == "legacy-unversioned"
        assert record.repository_slug is None
        assert record.branch is None
        assert record.findings == []

    def test_findings_list_is_copied(self):
        record = ScanRecord.from_dict(_mk_record_dict())
        assert len(record.findings) == 1
        assert isinstance(record.findings[0], FindingSnapshot)
        assert record.findings[0].id == "f1"


class TestScanRecordToDict:
    def test_to_dict_contains_expected_fields(self):
        record = ScanRecord.from_dict(_mk_record_dict())
        d = record.to_dict()
        assert d["scan_id"] == "scan-1"
        assert d["tenant_id"] == "local"
        assert d["repository_slug"] == "owner/demo"
        assert d["branch"] == "main"
        assert d["schema_version"] == SCHEMA_VERSION
        assert d["scoring_version"] == SCORING_VERSION
        assert d["finding_count"] == 1

    def test_to_dict_round_trip(self):
        record = ScanRecord.from_dict(_mk_record_dict())
        back = ScanRecord.from_dict(record.to_dict())
        assert back.scan_id == record.scan_id
        assert back.score == record.score
        assert back.grade == record.grade
        assert back.total_debt_points == record.total_debt_points
        assert back.finding_count == record.finding_count
        assert back.findings[0].id == record.findings[0].id
        assert back.category_scores == record.category_scores

    def test_to_dict_output_dicts_are_copies(self):
        record = ScanRecord.from_dict(_mk_record_dict())
        d = record.to_dict()
        d["category_scores"]["maintainability"] = 0
        d["findings"].clear()
        assert record.category_scores == {"maintainability": 750}
        assert len(record.findings) == 1


class TestScanRecordFromDictLegacyDefaults:
    def test_legacy_record_gets_defaults(self):
        data = _mk_record_dict()
        del data["tenant_id"]
        del data["repository_slug"]
        del data["branch"]
        del data["scoring_version"]
        record = ScanRecord.from_dict(data)
        assert record.tenant_id == LOCAL_TENANT_ID
        assert record.repository_slug is None
        assert record.branch is None
        assert record.scoring_version == "legacy-unversioned"

    def test_none_groupings_become_empty_dicts(self):
        data = _mk_record_dict(
            category_scores=None,
            severity_distribution=None,
            findings_by_category=None,
            findings_source_breakdown=None,
            findings=None,
        )
        record = ScanRecord.from_dict(data)
        assert record.category_scores == {}
        assert record.severity_distribution == {}
        assert record.findings_by_category == {}
        assert record.findings_source_breakdown == {}
        assert record.findings == []

    def test_score_and_counts_coerced_to_int(self):
        record = ScanRecord.from_dict(
            _mk_record_dict(
                score="750",
                total_debt_points="4",
                finding_count="1",
            )
        )
        assert record.score == 750
        assert record.total_debt_points == 4
        assert record.finding_count == 1


class TestBuildScanRecord:
    def test_defaults_scan_id_to_uuid_hex(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[],
            scoring=_mk_scoring(),
        )
        assert len(record.scan_id) == 32
        int(record.scan_id, 16)

    def test_default_scanned_at_is_utc_iso(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[],
            scoring=_mk_scoring(),
        )
        assert record.scanned_at.endswith("+00:00")
        assert "T" in record.scanned_at

    def test_explicit_scan_id_and_scanned_at_used(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[],
            scoring=_mk_scoring(),
            scan_id="fixed-id",
            scanned_at=_LEGACY_TS,
        )
        assert record.scan_id == "fixed-id"
        assert record.scanned_at == _LEGACY_TS

    def test_tenant_id_comes_from_current_tenant(self):
        bind_tenant("tenant-7")
        try:
            record = build_scan_record(
                repository_id="r1",
                repository_path="/repos/demo",
                findings=[],
                scoring=_mk_scoring(),
            )
            assert record.tenant_id == "tenant-7"
        finally:
            bind_tenant(LOCAL_TENANT_ID)

    def test_default_tenant_is_local(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[],
            scoring=_mk_scoring(),
        )
        assert record.tenant_id == LOCAL_TENANT_ID
        assert current_tenant_id() == LOCAL_TENANT_ID

    def test_slug_and_branch_passthrough(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[],
            scoring=_mk_scoring(),
            repository_slug="owner/demo",
            branch="feature/x",
        )
        assert record.repository_slug == "owner/demo"
        assert record.branch == "feature/x"

    def test_versions_and_scoring_mapped(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[_mk_finding()],
            scoring=_mk_scoring(finding_count=1, debt=4),
        )
        assert record.schema_version == SCHEMA_VERSION
        assert record.scoring_version == SCORING_VERSION
        assert record.score == 800
        assert record.grade == "A"
        assert record.finding_count == 1
        assert record.total_debt_points == 4

    def test_findings_become_redacted_snapshots(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[_mk_finding(evidence=f"token {_RAW_TOKEN}")],
            scoring=_mk_scoring(finding_count=1, debt=4),
        )
        assert len(record.findings) == 1
        snap = record.findings[0]
        assert isinstance(snap, FindingSnapshot)
        assert _RAW_TOKEN not in snap.evidence
        assert "[REDACTED]" in snap.evidence

    def test_empty_findings_produce_empty_record(self):
        record = build_scan_record(
            repository_id="r1",
            repository_path="/repos/demo",
            findings=[],
            scoring=_mk_scoring(),
        )
        assert record.findings == []
        assert record.finding_count == 0
        assert record.total_debt_points == 0
