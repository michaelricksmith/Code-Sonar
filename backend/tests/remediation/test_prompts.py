"""Unit tests for ``app.remediation.prompts``.

This is the dedicated test file for the prompt-first remediation module
(the deterministic fix-prompt generator plus the copy-event store and the
prompt-status reconciliation against the latest scan).

Existing related coverage:
- ``tests/api/test_remediation_api.py`` exercises the broader remediation
  pipeline, not this module's prompt template or event store.

Gaps this file covers:
- ``build_fix_prompt``: line ranges, evidence/suggestion/analyzer
  fallbacks, symbol rendering, determinism.
- Event store helpers: append/read round-trip, missing file, malformed
  lines, ``CODESONAR_HOME`` isolation, ``_copied_events`` filtering.
- Reconciliation helpers: ``_latest_copies`` newest-wins, ``_copy_status``
  branches, ``_status_items`` ordering, ``_latest_scan_index``,
  ``_resolve_latest_record`` direct hit and slug fallback.
- Endpoints: ``generate_fix_prompt`` and ``log_prompt_copied`` record
  events; ``prompt_status`` reconciles copies against a stubbed history
  store.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.remediation.prompts import (
    FindingPayload,
    FixPromptRequest,
    PromptCopiedRequest,
    _append_event,
    _copied_events,
    _copy_status,
    _data_root,
    _latest_copies,
    _latest_scan_index,
    _prompt_events_path,
    _read_events,
    _resolve_latest_record,
    _status_items,
    _utc_now_iso,
    build_fix_prompt,
    generate_fix_prompt,
    log_prompt_copied,
    prompt_status,
)


def _finding(**overrides) -> FindingPayload:
    base: dict = {
        "id": "f-1",
        "rule_id": "testing_debt:untested-module",
        "category": "testing",
        "severity": "info",
        "file_path": "backend/app/remediation/prompts.py",
        "line_start": 1,
        "line_end": 331,
        "symbol": None,
        "evidence": "x = 1",
        "message": "Module has no matching test file",
        "suggestion": "Add a test module under tests/",
        "analyzer": "testing_debt",
    }
    base.update(overrides)
    return FindingPayload(**base)


@pytest.fixture
def isolated_prompt_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the prompt event store at a throwaway CODESONAR_HOME."""
    monkeypatch.setenv("CODESONAR_HOME", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# build_fix_prompt
# ---------------------------------------------------------------------------


def test_build_fix_prompt_line_range():
    prompt = build_fix_prompt("michaelricksmith/Code-Sonar", _finding())
    assert "File: backend/app/remediation/prompts.py (lines 1-331)." in prompt
    assert "michaelricksmith/Code-Sonar" in prompt
    assert "Module has no matching test file" in prompt
    assert "testing_debt:untested-module" in prompt
    assert "x = 1" in prompt


def test_build_fix_prompt_single_line_when_start_equals_end():
    prompt = build_fix_prompt("repo", _finding(line_start=42, line_end=42))
    assert "(line 42)." in prompt
    assert "(lines 42-42)" not in prompt


def test_build_fix_prompt_single_line_when_end_missing():
    prompt = build_fix_prompt("repo", _finding(line_start=7, line_end=None))
    assert "(line 7)." in prompt


def test_build_fix_prompt_no_line_reference_when_start_missing():
    prompt = build_fix_prompt("repo", _finding(line_start=None, line_end=None))
    assert "(line" not in prompt
    assert "(lines" not in prompt


def test_build_fix_prompt_uses_suggestion_when_present():
    prompt = build_fix_prompt("repo", _finding(suggestion="Extract a helper."))
    assert "Extract a helper." in prompt


def test_build_fix_prompt_default_change_when_no_suggestion():
    prompt = build_fix_prompt("repo", _finding(suggestion=None))
    assert "smallest reasonable way" in prompt


def test_build_fix_prompt_evidence_fallback():
    prompt = build_fix_prompt("repo", _finding(evidence="   "))
    assert "(no code snippet available)" in prompt


def test_build_fix_prompt_analyzer_fallback():
    prompt = build_fix_prompt("repo", _finding(analyzer=""))
    assert "found by the code check check" in prompt


def test_build_fix_prompt_symbol_rendered():
    prompt = build_fix_prompt("repo", _finding(symbol="build_fix_prompt"))
    assert "In or near `build_fix_prompt`." in prompt


def test_build_fix_prompt_no_symbol_no_sentence():
    prompt = build_fix_prompt("repo", _finding(symbol=None))
    assert "In or near" not in prompt


def test_build_fix_prompt_deterministic():
    finding = _finding()
    assert build_fix_prompt("repo", finding) == build_fix_prompt("repo", finding)


# ---------------------------------------------------------------------------
# Event store helpers
# ---------------------------------------------------------------------------


def test_prompt_events_path_under_codesonar_home(isolated_prompt_store: Path):
    assert _prompt_events_path() == isolated_prompt_store / ".code-sonar" / "prompt-events.jsonl"
    assert _data_root() == isolated_prompt_store / ".code-sonar"


def test_append_and_read_events_roundtrip(isolated_prompt_store: Path):
    _append_event({"event": "generated", "finding_id": "f-1"})
    _append_event({"event": "copied", "finding_id": "f-1"})
    events = _read_events()
    assert [e["event"] for e in events] == ["generated", "copied"]
    assert all(e["finding_id"] == "f-1" for e in events)
    # Each record carries an ISO timestamp.
    assert all("at" in e for e in events)
    _utc_now_iso()  # smoke: returns a parseable timestamp
    assert "T" in _utc_now_iso()


def test_read_events_missing_file_returns_empty(isolated_prompt_store: Path):
    assert _read_events() == []


def test_read_events_skips_blank_and_malformed_lines(isolated_prompt_store: Path):
    path = _prompt_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "",
                "not json at all",
                json.dumps({"event": "copied", "finding_id": "f-2"}),
                "   ",
            ]
        ),
        encoding="utf-8",
    )
    events = _read_events()
    assert len(events) == 1
    assert events[0]["finding_id"] == "f-2"


def test_copied_events_filters_to_copies(isolated_prompt_store: Path):
    _append_event({"event": "generated", "finding_id": "f-1"})
    _append_event({"event": "copied", "finding_id": "f-1"})
    copied = _copied_events()
    assert len(copied) == 1
    assert copied[0]["event"] == "copied"


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------


def _copied(rule_id: str, file_path: str, at: str, finding_id: str = "f-1"):
    return {
        "event": "copied",
        "rule_id": rule_id,
        "file_path": file_path,
        "finding_id": finding_id,
        "at": at,
    }


def test_latest_copies_keeps_newest_per_key():
    events = [
        _copied("r1", "a.py", "2026-10-01T00:00:00+00:00", finding_id="f-old"),
        _copied("r1", "a.py", "2026-10-05T00:00:00+00:00", finding_id="f-new"),
        _copied("r2", "b.py", "2026-10-02T00:00:00+00:00"),
    ]
    latest = _latest_copies(events)
    assert set(latest) == {("r1", "a.py"), ("r2", "b.py")}
    assert latest[("r1", "a.py")]["finding_id"] == "f-new"


def test_latest_copies_skips_events_missing_key_parts():
    events = [
        {"event": "copied", "rule_id": "", "file_path": "a.py", "at": "2026-10-01T00:00:00+00:00"},
        {"event": "copied", "rule_id": "r1", "file_path": "", "at": "2026-10-01T00:00:00+00:00"},
    ]
    assert _latest_copies(events) == {}


def test_copy_status_in_progress_without_record():
    result = _copy_status("2026-10-05T00:00:00+00:00", None, "", ("r1", "a.py"), set())
    assert result == "in_progress"


def test_copy_status_in_progress_when_scan_not_newer():
    record = SimpleNamespace()
    assert (
        _copy_status(
            "2026-10-06T00:00:00+00:00",
            record,
            "2026-10-05T00:00:00+00:00",
            ("r1", "a.py"),
            set(),
        )
        == "in_progress"
    )


def test_copy_status_still_open():
    record = SimpleNamespace()
    assert (
        _copy_status(
            "2026-10-05T00:00:00+00:00",
            record,
            "2026-10-06T00:00:00+00:00",
            ("r1", "a.py"),
            {("r1", "a.py")},
        )
        == "still_open"
    )


def test_copy_status_resolved():
    record = SimpleNamespace()
    assert (
        _copy_status(
            "2026-10-05T00:00:00+00:00",
            record,
            "2026-10-06T00:00:00+00:00",
            ("r1", "a.py"),
            set(),
        )
        == "resolved"
    )


def test_status_items_sorted_newest_first():
    latest_copy = {
        ("r1", "a.py"): _copied("r1", "a.py", "2026-10-01T00:00:00+00:00"),
        ("r2", "b.py"): _copied("r2", "b.py", "2026-10-05T00:00:00+00:00"),
    }
    items = _status_items(latest_copy, None, "", set())
    assert [i["rule_id"] for i in items] == ["r2", "r1"]
    assert items[0]["status"] == "in_progress"
    assert items[0]["copied_at"] == "2026-10-05T00:00:00+00:00"


def test_latest_scan_index_none_record():
    assert _latest_scan_index(None) == ("", set())


def test_latest_scan_index_collects_finding_keys():
    record = SimpleNamespace(
        scanned_at="2026-10-06T00:00:00+00:00",
        findings=[
            SimpleNamespace(rule_id="r1", file_path="a.py"),
            SimpleNamespace(rule_id="r2", file_path="b.py"),
        ],
    )
    scanned_at, keys = _latest_scan_index(record)
    assert scanned_at == "2026-10-06T00:00:00+00:00"
    assert keys == {("r1", "a.py"), ("r2", "b.py")}


def _fake_store(latest=None, all_records=()):
    """Minimal history-store double with ``latest``/``load_all``."""
    records = list(all_records)
    return SimpleNamespace(
        latest=lambda repository_id: latest,
        load_all=lambda: list(records),
    )


def test_resolve_latest_record_direct_hit():
    record = SimpleNamespace(scanned_at="2026-10-06T00:00:00+00:00")
    assert _resolve_latest_record(_fake_store(latest=record), "owner/repo", "id-1") is record


def test_resolve_latest_record_slug_fallback_picks_newest():
    older = SimpleNamespace(repository_slug="owner/repo", scanned_at="2026-10-01T00:00:00+00:00")
    newer = SimpleNamespace(repository_slug="Owner/Repo", scanned_at="2026-10-06T00:00:00+00:00")
    other = SimpleNamespace(repository_slug="other/repo", scanned_at="2026-10-07T00:00:00+00:00")
    store = _fake_store(all_records=[older, newer, other])
    assert _resolve_latest_record(store, "owner/repo", "id-1") is newer


def test_resolve_latest_record_no_match_returns_none():
    assert _resolve_latest_record(_fake_store(), "owner/repo", "id-1") is None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def test_generate_fix_prompt_endpoint_records_event(isolated_prompt_store: Path):
    request = FixPromptRequest(
        repository="michaelricksmith/Code-Sonar",
        scan_id="s-1",
        finding=_finding(),
    )
    result = await generate_fix_prompt(request)
    assert "michaelricksmith/Code-Sonar" in result["prompt"]
    assert "(lines 1-331)" in result["prompt"]
    events = _read_events()
    assert len(events) == 1
    assert events[0]["event"] == "generated"
    assert events[0]["finding_id"] == "f-1"
    assert events[0]["scan_id"] == "s-1"


async def test_log_prompt_copied_endpoint_records_event(isolated_prompt_store: Path):
    request = PromptCopiedRequest(
        repository="michaelricksmith/Code-Sonar",
        scan_id="s-1",
        finding_id="f-1",
        rule_id="testing_debt:untested-module",
        file_path="backend/app/remediation/prompts.py",
        line_start=1,
    )
    result = await log_prompt_copied(request)
    assert result == {"ok": True}
    events = _copied_events()
    assert len(events) == 1
    assert events[0]["finding_id"] == "f-1"
    assert events[0]["rule_id"] == "testing_debt:untested-module"


async def test_prompt_status_endpoint_reconciles_against_stubbed_store(
    isolated_prompt_store: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.history.repository_identity as identity_mod
    import app.main

    # A copied prompt from before the latest scan; the finding is gone there.
    _append_event(
        {
            "event": "copied",
            "at": "2026-10-01T00:00:00+00:00",
            "repository": "michaelricksmith/Code-Sonar",
            "finding_id": "f-9",
            "rule_id": "testing_debt:untested-module",
            "file_path": "backend/app/remediation/prompts.py",
            "line_start": 1,
        }
    )
    record = SimpleNamespace(
        scanned_at="2026-10-06T00:00:00+00:00",
        findings=[],
    )
    monkeypatch.setattr(identity_mod, "compute_repository_id_for_slug", lambda slug: "repo-id-1")
    monkeypatch.setattr(app.main, "get_history_store", lambda: _fake_store(latest=record))

    result = await prompt_status(repository="michaelricksmith/Code-Sonar")
    assert result["repository"] == "michaelricksmith/Code-Sonar"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["finding_id"] == "f-9"
    assert item["status"] == "resolved"
    assert item["copied_at"] == "2026-10-01T00:00:00+00:00"
