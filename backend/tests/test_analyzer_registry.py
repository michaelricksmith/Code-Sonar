"""Analyzer registry integrity tests.

These tests guard the registry surface that powers the analyzer
metadata endpoint and the React dashboard's "Analyzers" panel. They
ensure the order is stable, the metadata is consumable, and each
registered analyzer has a unique name.
"""

from __future__ import annotations

from app.services.repository import (
    get_analyzer_metadata,
    get_registered_analyzers,
)


class TestAnalyzerRegistry:

    def test_registry_non_empty(self):
        assert len(get_registered_analyzers()) > 0

    def test_metadata_covers_every_registered_analyzer(self):
        registered = get_registered_analyzers()
        metadata = get_analyzer_metadata()
        assert len(metadata) == len(registered)

    def test_metadata_unique_ids(self):
        metadata = get_analyzer_metadata()
        ids = [m["analyzer_id"] for m in metadata]
        assert len(ids) == len(set(ids)), f"Duplicate analyzer ids: {ids}"

    def test_metadata_required_keys(self):
        for entry in get_analyzer_metadata():
            assert "name" in entry
            assert "analyzer_id" in entry
            assert "category" in entry
            assert "threshold" in entry
            # `threshold` may be None for analyzers without a numeric threshold.
            assert entry["threshold"] is None or isinstance(entry["threshold"], int)

    def test_metadata_analyzer_id_matches_name(self):
        # Convention: name == analyzer_id for stable dashboard matching.
        for entry in get_analyzer_metadata():
            assert entry["analyzer_id"] == entry["name"]

    def test_registry_order_stable(self):
        first = get_analyzer_metadata()
        second = get_analyzer_metadata()
        third = get_analyzer_metadata()
        ids_first = [m["analyzer_id"] for m in first]
        ids_second = [m["analyzer_id"] for m in second]
        ids_third = [m["analyzer_id"] for m in third]
        assert ids_first == ids_second == ids_third

    def test_registry_includes_expected_analyzers(self):
        names = {m["analyzer_id"] for m in get_analyzer_metadata()}
        # The currently expected analyzers per the build-mode backlog:
        for expected in (
            "comment_markers",
            "oversized_files",
            "oversized_functions",
            "cyclomatic_complexity",
            "nesting_depth",
            "testing_debt",
        ):
            assert expected in names, (
                f"Expected analyzer {expected!r} missing from registry"
            )
