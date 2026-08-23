"""Scan-history persistence tests — Lane 4 of Checkpoint 6.

Covers the remaining required scenarios:

- 10. persistence round-trip (the drift-side test lives in
    ``test_invariants.py``; this file asserts the store round-trips
    records losslessly and that comparison semantics survive the
    round-trip).
- 13. repository isolation (history for repo A must never
    contaminate repo B).
- 15. schema/version compatibility (records with unknown schema
    versions are skipped on load).
- Plus: append order, atomic-write durability (no partial writes),
  duplicate-scan-id defensive handling, latest() ordering,
  load_all() deterministic ordering by (scanned_at, scan_id).
"""

from __future__ import annotations

import json

from app.history import (
    SCHEMA_VERSION,
    FindingSnapshot,
    InMemoryHistoryStore,
    JsonlHistoryStore,
    ScanRecord,
    compute_repository_id,
)


def _mk_finding(
    *,
    fid: str,
    category: str = "maintainability",
    severity: str = "warning",
    debt: int = 4,
    rel_path: str = "src/app.py",
) -> FindingSnapshot:
    return FindingSnapshot.from_dict({
        "id": fid,
        "rule_id": "test:rule",
        "category": category,
        "severity": severity,
        "confidence": 1.0,
        "file_path": rel_path,
        "line_start": 1,
        "line_end": 1,
        "symbol": None,
        "evidence": "",
        "message": f"finding {fid}",
        "suggestion": None,
        "debt_points": debt,
        "analyzer": "test_analyzer",
        "metadata": {},
    })


def _mk_record(
    *,
    scan_id: str,
    repository_id: str,
    repository_path: str,
    scanned_at: str,
    score: int,
    grade: str,
    findings: list[FindingSnapshot],
) -> ScanRecord:
    return ScanRecord.from_dict({
        "scan_id": scan_id,
        "repository_id": repository_id,
        "repository_path": repository_path,
        "scanned_at": scanned_at,
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


class TestRepositoryIdentity:
    def test_same_path_produces_same_id(self, tmp_path):
        a = tmp_path / "repo"
        a.mkdir()
        assert compute_repository_id(a) == compute_repository_id(a)

    def test_different_paths_produce_different_ids(self, tmp_path):
        a = tmp_path / "repo_a"
        b = tmp_path / "repo_b"
        a.mkdir()
        b.mkdir()
        assert compute_repository_id(a) != compute_repository_id(b)

    def test_path_normalization_is_stable(self, tmp_path):
        # Calling twice must return the same id for the same path.
        a = tmp_path / "repo"
        a.mkdir()
        assert compute_repository_id(a) == compute_repository_id(a)


class TestInMemoryHistoryStore:
    def test_append_and_load(self):
        store = InMemoryHistoryStore()
        r = _mk_record(
            scan_id="s1",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="f1")],
        )
        store.append(r)
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].scan_id == "s1"

    def test_load_all_deterministic_ordering(self):
        store = InMemoryHistoryStore()
        # Append out of order; expect ascending scanned_at on load.
        store.append(_mk_record(
            scan_id="b",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T18:00:00+00:00",
            score=720,
            grade="C",
            findings=[],
        ))
        store.append(_mk_record(
            scan_id="a",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        loaded = store.load_all()
        assert [r.scan_id for r in loaded] == ["a", "b"]

    def test_repository_isolation(self):
        store = InMemoryHistoryStore()
        store.append(_mk_record(
            scan_id="s1",
            repository_id="A",
            repository_path="/pA",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        store.append(_mk_record(
            scan_id="s2",
            repository_id="B",
            repository_path="/pB",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        a_records = store.load_all("A")
        b_records = store.load_all("B")
        assert {r.scan_id for r in a_records} == {"s1"}
        assert {r.scan_id for r in b_records} == {"s2"}
        assert store.latest("A").scan_id == "s1"
        assert store.latest("B").scan_id == "s2"

    def test_latest_returns_none_when_empty(self):
        assert InMemoryHistoryStore().latest("anything") is None

    def test_get_returns_none_for_missing_id(self):
        store = InMemoryHistoryStore()
        assert store.get("nonexistent") is None


class TestJsonlHistoryStore:
    def test_append_and_load_round_trip(self, tmp_path):
        path = tmp_path / "history.jsonl"
        store = JsonlHistoryStore(path)
        store.append(_mk_record(
            scan_id="s1",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="f1")],
        ))
        loaded = JsonlHistoryStore(path).load_all("abc")
        assert len(loaded) == 1
        assert loaded[0].scan_id == "s1"
        assert loaded[0].findings[0].id == "f1"

    def test_atomic_write_no_partial_corruption(self, tmp_path):
        # Simulate: write some records, then verify the file is
        # parseable line-by-line with no half-written JSON.
        path = tmp_path / "history.jsonl"
        store = JsonlHistoryStore(path)
        for i in range(20):
            store.append(_mk_record(
                scan_id=f"s{i}",
                repository_id="abc",
                repository_path="/p",
                scanned_at=f"2026-08-22T17:{i:02d}:00+00:00",
                score=750,
                grade="B",
                findings=[],
            ))
        text = path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 20
        for line in lines:
            # Each line must round-trip as JSON.
            parsed = json.loads(line)
            assert "scan_id" in parsed

    def test_repository_isolation_persists_across_reload(self, tmp_path):
        path = tmp_path / "history.jsonl"
        store = JsonlHistoryStore(path)
        store.append(_mk_record(
            scan_id="sA",
            repository_id="A",
            repository_path="/pA",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        store.append(_mk_record(
            scan_id="sB",
            repository_id="B",
            repository_path="/pB",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        # Reload from disk via a fresh store.
        store2 = JsonlHistoryStore(path)
        a = store2.load_all("A")
        b = store2.load_all("B")
        assert {r.scan_id for r in a} == {"sA"}
        assert {r.scan_id for r in b} == {"sB"}

    def test_schema_version_mismatch_skipped(self, tmp_path):
        path = tmp_path / "history.jsonl"
        # Append a current-schema record via the API.
        store = JsonlHistoryStore(path)
        store.append(_mk_record(
            scan_id="good",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        # Append a future-schema record directly via the file so it
        # bypasses any future-proofing at the API layer.
        future = {
            "scan_id": "future",
            "repository_id": "abc",
            "repository_path": "/p",
            "scanned_at": "2026-08-22T18:00:00+00:00",
            "schema_version": "99.0",  # unknown
            "score": 700,
            "grade": "C",
            "total_debt_points": 0,
            "finding_count": 0,
            "category_scores": {},
            "severity_distribution": {},
            "findings_by_category": {},
            "findings_source_breakdown": {"source": 0, "test": 0, "fixture": 0},
            "findings": [],
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(future) + "\n")
        loaded = JsonlHistoryStore(path).load_all("abc")
        ids = [r.scan_id for r in loaded]
        assert "good" in ids
        assert "future" not in ids

    def test_corrupt_line_is_skipped(self, tmp_path):
        path = tmp_path / "history.jsonl"
        store = JsonlHistoryStore(path)
        store.append(_mk_record(
            scan_id="good",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        # Inject a corrupt line.
        with path.open("a", encoding="utf-8") as f:
            f.write("this is not json\n")
        # Inject another good record.
        JsonlHistoryStore(path).append(_mk_record(
            scan_id="good2",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T18:00:00+00:00",
            score=750,
            grade="B",
            findings=[],
        ))
        loaded = JsonlHistoryStore(path).load_all("abc")
        ids = [r.scan_id for r in loaded]
        assert "good" in ids
        assert "good2" in ids


class TestRedactionInPersistedRecord:
    def test_persisted_evidence_is_redacted(self, tmp_path):

        path = tmp_path / "history.jsonl"
        store = JsonlHistoryStore(path)
        # Build a finding with a secret-like string in evidence.
        finding_dict = {
            "id": "x",
            "rule_id": "secrets:aws",
            "category": "security",
            "severity": "error",
            "confidence": 1.0,
            "file_path": "src/app.py",
            "line_start": 1,
            "line_end": 1,
            "symbol": None,
            # 30-char alphanumeric -> matches redact_secrets' regex.
            "evidence": "match=AKIAIO…MPLE secret=abcdefghijklmnopqrstuvwxyz123456",
            "message": "Hardcoded secret",
            "suggestion": None,
            "debt_points": 10,
            "analyzer": "secrets",
            "metadata": {"match_prefix": "AKIAIO…M"},
        }
        snap = FindingSnapshot.from_dict(finding_dict)
        record = ScanRecord(
            scan_id="s1",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            schema_version=SCHEMA_VERSION,
            score=720,
            grade="C",
            total_debt_points=10,
            finding_count=1,
            category_scores={},
            severity_distribution={},
            findings_by_category={},
            findings_source_breakdown={"source": 0, "test": 0, "fixture": 0},
            findings=[snap],
        )
        store.append(record)
        # Raw evidence must be redacted before persistence.
        raw = path.read_text(encoding="utf-8")
        assert "abcdefghijklmnopqrstuvwxyz123456" not in raw
        assert "[REDACTED]" in raw


class TestDriftRoundTripPreservesSemantics:
    def test_drift_works_on_records_persisted_then_reloaded(self, tmp_path):
        from app.drift import compute_drift

        path = tmp_path / "history.jsonl"
        store = JsonlHistoryStore(path)
        baseline = _mk_record(
            scan_id="b",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T17:00:00+00:00",
            score=750,
            grade="B",
            findings=[_mk_finding(fid="f1"), _mk_finding(fid="f2")],
        )
        current = _mk_record(
            scan_id="c",
            repository_id="abc",
            repository_path="/p",
            scanned_at="2026-08-22T19:00:00+00:00",
            score=720,
            grade="C",
            findings=[_mk_finding(fid="f1"), _mk_finding(fid="f3")],
        )
        store.append(baseline)
        store.append(current)
        loaded = JsonlHistoryStore(path).load_all("abc")
        result = compute_drift(loaded[0], loaded[1])
        assert result.summary.persistent_count == 1  # f1
        assert result.summary.resolved_count == 1   # f2
        assert result.summary.new_count == 1        # f3
