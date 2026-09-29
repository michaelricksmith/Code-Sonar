"""Tests for comment_markers analyzer.

Tests verify:
- Deterministic behavior (same input → same output)
- Correct detection of TODO, FIXME, HACK markers
- Binary file handling
- Encoding error handling
- Line number accuracy
- Finding schema validation
"""


import pytest

from app.models.finding import Finding, FindingCategory, FindingSeverity

# These tests assume comment_markers analyzer will be implemented by VP Engineering
# with the following interface:
#
# from app.analyzers.comment_markers import CommentMarkersAnalyzer
#
# analyzer = CommentMarkersAnalyzer()
# findings: list[Finding] = await analyzer.analyze(repo_path: Path)


class TestCommentMarkersAnalyzer:
    """Test suite for comment_markers analyzer."""

    def _make_analyzer(self):
        """Create a CommentMarkersAnalyzer instance."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        return CommentMarkersAnalyzer()

    @staticmethod
    def _finding_sort_key(finding):
        """Sort key for ordering findings by file, then line."""
        return (finding.file_path, finding.line_start or 0)

    @staticmethod
    def _assert_findings_match(first, second):
        """Assert two findings carry identical identifying details."""
        assert first.rule_id == second.rule_id
        assert first.file_path == second.file_path
        assert first.line_start == second.line_start
        assert first.evidence == second.evidence
        assert first.category == second.category
        assert first.severity == second.severity

    @staticmethod
    def _marker_findings(findings, marker, filename=None):
        """Filter findings whose evidence mentions marker, optionally in one file."""
        marker_upper = marker.upper()
        return [
            f for f in findings
            if marker_upper in f.evidence.upper()
            and (filename is None or f.file_path.endswith(filename))
        ]

    @staticmethod
    def _finding_at_line(findings, line):
        """Return the first finding reported at the given line, if any."""
        return next((f for f in findings if f.line_start == line), None)

    @staticmethod
    def _assert_finding_identity_fields(finding):
        """Assert the finding is a Finding with required identity fields."""
        assert isinstance(finding, Finding)
        assert finding.id
        assert finding.rule_id
        assert finding.analyzer == "comment_markers"

    @staticmethod
    def _assert_finding_enum_fields(finding):
        """Assert the finding's category and severity are valid enum values."""
        assert finding.category in FindingCategory
        assert finding.severity in FindingSeverity

    @staticmethod
    def _assert_finding_numeric_fields(finding):
        """Assert the finding's numeric fields are within valid ranges."""
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.debt_points >= 0

    @staticmethod
    def _assert_finding_text_fields(finding):
        """Assert the finding's required text fields are present."""
        assert finding.file_path
        assert finding.evidence
        assert finding.message

    @pytest.mark.asyncio
    async def test_determinism_same_finding_count(self, test_repo_fixture):
        """Test that analyzing the same repo twice finds the same number of markers."""
        analyzer = self._make_analyzer()

        # Run analysis twice
        findings_1 = analyzer.analyze(test_repo_fixture)
        findings_2 = analyzer.analyze(test_repo_fixture)

        # Should produce identical results
        assert len(findings_1) == len(findings_2)

    @pytest.mark.asyncio
    async def test_determinism_same_finding_details(self, test_repo_fixture):
        """Test that analyzing the same repo twice finds identical details."""
        analyzer = self._make_analyzer()

        # Run analysis twice
        findings_1 = analyzer.analyze(test_repo_fixture)
        findings_2 = analyzer.analyze(test_repo_fixture)

        # Sort by file_path and line_start for comparison
        findings_1_sorted = sorted(findings_1, key=self._finding_sort_key)
        findings_2_sorted = sorted(findings_2, key=self._finding_sort_key)

        for f1, f2 in zip(findings_1_sorted, findings_2_sorted):
            self._assert_findings_match(f1, f2)

    @pytest.mark.asyncio
    async def test_detects_todo_in_python(self, test_repo_fixture):
        """Test that TODO markers are detected in Python files."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Filter to TODO findings
        todo_findings = self._marker_findings(findings, "TODO")

        assert len(todo_findings) > 0, "Should detect at least one TODO"

        # Check main.py TODO
        main_py_todos = self._marker_findings(todo_findings, "TODO", "main.py")
        assert len(main_py_todos) >= 1, "Should detect TODO in main.py"

        # Verify TODO at line 4
        line_4_todo = self._finding_at_line(main_py_todos, 4)
        assert line_4_todo is not None, "Should detect TODO at line 4"
        assert "input validation" in line_4_todo.evidence.lower()

    @pytest.mark.asyncio
    async def test_detects_fixme_in_python(self, test_repo_fixture):
        """Test that FIXME markers are detected in Python files."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Filter to FIXME findings
        fixme_findings = self._marker_findings(findings, "FIXME")

        assert len(fixme_findings) > 0, "Should detect at least one FIXME"

        # Check main.py FIXME
        main_py_fixmes = self._marker_findings(fixme_findings, "FIXME", "main.py")
        assert len(main_py_fixmes) >= 1, "Should detect FIXME in main.py"

        # Verify FIXME at line 6
        line_6_fixme = self._finding_at_line(main_py_fixmes, 6)
        assert line_6_fixme is not None, "Should detect FIXME at line 6"
        assert "inefficient" in line_6_fixme.evidence.lower()

    @pytest.mark.asyncio
    async def test_detects_hack_in_python(self, test_repo_fixture):
        """Test that HACK markers are detected in Python files."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Filter to HACK findings
        hack_findings = self._marker_findings(findings, "HACK")

        assert len(hack_findings) > 0, "Should detect at least one HACK"

        # Check main.py HACK
        main_py_hacks = self._marker_findings(hack_findings, "HACK", "main.py")
        assert len(main_py_hacks) >= 1, "Should detect HACK in main.py"

        # Verify HACK at line 8
        line_8_hack = self._finding_at_line(main_py_hacks, 8)
        assert line_8_hack is not None, "Should detect HACK at line 8"
        assert "workaround" in line_8_hack.evidence.lower()

    @pytest.mark.asyncio
    async def test_ignores_binary_files(self, test_repo_fixture):
        """Test that binary files are not analyzed."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # No findings should come from binary files
        binary_findings = [
            f for f in findings
            if f.file_path.endswith(".png")
        ]

        assert len(binary_findings) == 0, "Should not analyze binary files"

    @pytest.mark.asyncio
    async def test_handles_encoding_errors_gracefully(self, test_repo_fixture):
        """Test that files with encoding errors don't crash the analyzer."""
        # Create a file with invalid UTF-8
        bad_file = test_repo_fixture / "bad_encoding.py"
        bad_file.write_bytes(b'# TODO: Fix this\n\xff\xfe\x00\x00')

        analyzer = self._make_analyzer()

        # Should not raise exception
        findings = analyzer.analyze(test_repo_fixture)

        # Should still detect the TODO if possible, or skip the file gracefully
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_line_numbers_are_one_indexed(self, test_repo_fixture):
        """Test that all reported line numbers are positive (1-indexed)."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # All findings should have positive line numbers
        for finding in findings:
            if finding.line_start is not None:
                assert finding.line_start > 0, f"Line numbers should be 1-indexed: {finding}"

    @pytest.mark.asyncio
    async def test_returns_expected_line_numbers(self, test_repo_fixture):
        """Test that markers are reported at the expected lines in main.py."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Verify specific line numbers match test_repo_fixture
        main_py_findings = [f for f in findings if f.file_path.endswith("main.py")]
        line_numbers = sorted([f.line_start for f in main_py_findings if f.line_start])

        # Expected lines: 4 (TODO), 6 (FIXME), 8 (HACK)
        assert 4 in line_numbers, "Should detect marker at line 4"
        assert 6 in line_numbers, "Should detect marker at line 6"
        assert 8 in line_numbers, "Should detect marker at line 8"

    @pytest.mark.asyncio
    async def test_finding_schema_identity_fields(self, test_repo_fixture):
        """Test that findings are Finding instances with identity fields set."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        for finding in findings:
            self._assert_finding_identity_fields(finding)

    @pytest.mark.asyncio
    async def test_finding_schema_enum_fields(self, test_repo_fixture):
        """Test that findings carry valid category and severity enums."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        for finding in findings:
            self._assert_finding_enum_fields(finding)

    @pytest.mark.asyncio
    async def test_finding_schema_numeric_fields(self, test_repo_fixture):
        """Test that findings' numeric fields stay within valid ranges."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        for finding in findings:
            self._assert_finding_numeric_fields(finding)

    @pytest.mark.asyncio
    async def test_finding_schema_text_fields(self, test_repo_fixture):
        """Test that findings' required text fields are present."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        for finding in findings:
            self._assert_finding_text_fields(finding)

    @pytest.mark.asyncio
    async def test_finding_schema_pydantic_round_trip(self, test_repo_fixture):
        """Test that findings survive a Pydantic dump/validate round trip."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        for finding in findings:
            # Pydantic validation should pass
            Finding.model_validate(finding.model_dump())

    @pytest.mark.asyncio
    async def test_detects_markers_in_subdirectories(self, test_repo_fixture):
        """Test that markers are detected in nested subdirectories."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Should find TODO in src/module.py
        subdir_findings = [
            f for f in findings
            if "src" in f.file_path and f.file_path.endswith("module.py")
        ]

        assert len(subdir_findings) > 0, "Should detect markers in subdirectories"

    @pytest.mark.asyncio
    async def test_empty_repository_returns_empty_list(self, tmp_path):
        """Test that analyzing an empty repository returns no findings."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(tmp_path)

        assert findings == [], "Empty repository should return empty list"

    @pytest.mark.asyncio
    async def test_file_without_markers_returns_no_findings(self, test_repo_fixture):
        """Test that clean files without markers return no findings."""
        analyzer = self._make_analyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # utils.py has no markers
        utils_findings = [
            f for f in findings
            if f.file_path.endswith("utils.py")
        ]

        assert len(utils_findings) == 0, "Clean file should have no findings"
