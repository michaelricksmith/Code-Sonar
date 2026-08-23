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

    @pytest.mark.asyncio
    async def test_determinism_same_input_same_output(self, test_repo_fixture):
        """Test that analyzing the same repo twice produces identical results."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()

        # Run analysis twice
        findings_1 = analyzer.analyze(test_repo_fixture)
        findings_2 = analyzer.analyze(test_repo_fixture)

        # Should produce identical results
        assert len(findings_1) == len(findings_2)

        # Sort by file_path and line_start for comparison
        findings_1_sorted = sorted(findings_1, key=lambda f: (f.file_path, f.line_start or 0))
        findings_2_sorted = sorted(findings_2, key=lambda f: (f.file_path, f.line_start or 0))

        for f1, f2 in zip(findings_1_sorted, findings_2_sorted):
            assert f1.rule_id == f2.rule_id
            assert f1.file_path == f2.file_path
            assert f1.line_start == f2.line_start
            assert f1.evidence == f2.evidence
            assert f1.category == f2.category
            assert f1.severity == f2.severity

    @pytest.mark.asyncio
    async def test_detects_todo_in_python(self, test_repo_fixture):
        """Test that TODO markers are detected in Python files."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Filter to TODO findings
        todo_findings = [f for f in findings if "TODO" in f.evidence.upper()]

        assert len(todo_findings) > 0, "Should detect at least one TODO"

        # Check main.py TODO
        main_py_todos = [
            f for f in todo_findings
            if f.file_path.endswith("main.py")
        ]
        assert len(main_py_todos) >= 1, "Should detect TODO in main.py"

        # Verify TODO at line 4
        line_4_todo = next((f for f in main_py_todos if f.line_start == 4), None)
        assert line_4_todo is not None, "Should detect TODO at line 4"
        assert "input validation" in line_4_todo.evidence.lower()

    @pytest.mark.asyncio
    async def test_detects_fixme_in_python(self, test_repo_fixture):
        """Test that FIXME markers are detected in Python files."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Filter to FIXME findings
        fixme_findings = [f for f in findings if "FIXME" in f.evidence.upper()]

        assert len(fixme_findings) > 0, "Should detect at least one FIXME"

        # Check main.py FIXME
        main_py_fixmes = [
            f for f in fixme_findings
            if f.file_path.endswith("main.py")
        ]
        assert len(main_py_fixmes) >= 1, "Should detect FIXME in main.py"

        # Verify FIXME at line 6
        line_6_fixme = next((f for f in main_py_fixmes if f.line_start == 6), None)
        assert line_6_fixme is not None, "Should detect FIXME at line 6"
        assert "inefficient" in line_6_fixme.evidence.lower()

    @pytest.mark.asyncio
    async def test_detects_hack_in_python(self, test_repo_fixture):
        """Test that HACK markers are detected in Python files."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # Filter to HACK findings
        hack_findings = [f for f in findings if "HACK" in f.evidence.upper()]

        assert len(hack_findings) > 0, "Should detect at least one HACK"

        # Check main.py HACK
        main_py_hacks = [
            f for f in hack_findings
            if f.file_path.endswith("main.py")
        ]
        assert len(main_py_hacks) >= 1, "Should detect HACK in main.py"

        # Verify HACK at line 8
        line_8_hack = next((f for f in main_py_hacks if f.line_start == 8), None)
        assert line_8_hack is not None, "Should detect HACK at line 8"
        assert "workaround" in line_8_hack.evidence.lower()

    @pytest.mark.asyncio
    async def test_ignores_binary_files(self, test_repo_fixture):
        """Test that binary files are not analyzed."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
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
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        # Create a file with invalid UTF-8
        bad_file = test_repo_fixture / "bad_encoding.py"
        bad_file.write_bytes(b'# TODO: Fix this\n\xff\xfe\x00\x00')

        analyzer = CommentMarkersAnalyzer()

        # Should not raise exception
        findings = analyzer.analyze(test_repo_fixture)

        # Should still detect the TODO if possible, or skip the file gracefully
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_returns_correct_line_numbers(self, test_repo_fixture):
        """Test that line numbers are accurate (1-indexed)."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # All findings should have positive line numbers
        for finding in findings:
            if finding.line_start is not None:
                assert finding.line_start > 0, f"Line numbers should be 1-indexed: {finding}"

        # Verify specific line numbers match test_repo_fixture
        main_py_findings = [f for f in findings if f.file_path.endswith("main.py")]
        line_numbers = sorted([f.line_start for f in main_py_findings if f.line_start])

        # Expected lines: 4 (TODO), 6 (FIXME), 8 (HACK)
        assert 4 in line_numbers, "Should detect marker at line 4"
        assert 6 in line_numbers, "Should detect marker at line 6"
        assert 8 in line_numbers, "Should detect marker at line 8"

    @pytest.mark.asyncio
    async def test_finding_schema_validates(self, test_repo_fixture):
        """Test that all returned findings conform to Finding schema."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(test_repo_fixture)

        for finding in findings:
            # Should be a Finding instance
            assert isinstance(finding, Finding)

            # Required fields must be present
            assert finding.id
            assert finding.rule_id
            assert finding.category in FindingCategory
            assert finding.severity in FindingSeverity
            assert 0.0 <= finding.confidence <= 1.0
            assert finding.file_path
            assert finding.evidence
            assert finding.message
            assert finding.debt_points >= 0
            assert finding.analyzer == "comment_markers"

            # Pydantic validation should pass
            Finding.model_validate(finding.model_dump())

    @pytest.mark.asyncio
    async def test_detects_markers_in_subdirectories(self, test_repo_fixture):
        """Test that markers are detected in nested subdirectories."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
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
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(tmp_path)

        assert findings == [], "Empty repository should return empty list"

    @pytest.mark.asyncio
    async def test_file_without_markers_returns_no_findings(self, test_repo_fixture):
        """Test that clean files without markers return no findings."""
        from app.analyzers.comment_markers import CommentMarkersAnalyzer

        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(test_repo_fixture)

        # utils.py has no markers
        utils_findings = [
            f for f in findings
            if f.file_path.endswith("utils.py")
        ]

        assert len(utils_findings) == 0, "Clean file should have no findings"
