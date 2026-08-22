"""Pytest configuration and shared fixtures."""

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.models.finding import Finding, FindingCategory, FindingSeverity


@pytest.fixture
def test_repo_fixture() -> Generator[Path, None, None]:
    """Create a temporary test repository with known files.
    
    Yields:
        Path to temporary test repository root
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        
        # Create Python file with TODO comments
        python_file = repo_path / "main.py"
        python_file.write_text(
            '"""Sample Python module."""\n'
            '\n'
            'def process_data():\n'
            '    # TODO: Add input validation\n'
            '    data = get_data()\n'
            '    # FIXME: This is inefficient\n'
            '    result = [x * 2 for x in data]\n'
            '    # HACK: Temporary workaround\n'
            '    return result\n'
            '\n'
            'def get_data():\n'
            '    return [1, 2, 3]\n',
            encoding='utf-8'
        )
        
        # Create JavaScript file with markers
        js_file = repo_path / "app.js"
        js_file.write_text(
            '// TODO: Refactor this function\n'
            'function processUser(user) {\n'
            '  // FIXME: Add error handling\n'
            '  return user.name.toUpperCase();\n'
            '}\n',
            encoding='utf-8'
        )
        
        # Create file without markers
        clean_file = repo_path / "utils.py"
        clean_file.write_text(
            '"""Utilities module."""\n'
            '\n'
            'def add(a, b):\n'
            '    """Add two numbers."""\n'
            '    return a + b\n',
            encoding='utf-8'
        )
        
        # Create binary file (should be ignored)
        binary_file = repo_path / "image.png"
        binary_file.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
        
        # Create subdirectory with file
        subdir = repo_path / "src"
        subdir.mkdir()
        sub_file = subdir / "module.py"
        sub_file.write_text(
            '# TODO: Implement feature\n'
            'pass\n',
            encoding='utf-8'
        )
        
        yield repo_path


@pytest.fixture
def sample_findings_fixture() -> list[Finding]:
    """Return sample Finding objects for testing.
    
    Returns:
        List of sample Finding instances
    """
    return [
        Finding(
            id="finding_001",
            rule_id="comment:todo",
            category=FindingCategory.MAINTAINABILITY,
            severity=FindingSeverity.INFO,
            confidence=1.0,
            file_path="main.py",
            line_start=4,
            line_end=4,
            symbol=None,
            evidence="TODO: Add input validation",
            message="TODO comment found",
            suggestion="Address the TODO or remove the comment",
            debt_points=1,
            remediation_effort="15 minutes",
            analyzer="comment_markers",
            metadata={"marker_type": "TODO", "content": "Add input validation"},
        ),
        Finding(
            id="finding_002",
            rule_id="comment:fixme",
            category=FindingCategory.MAINTAINABILITY,
            severity=FindingSeverity.WARNING,
            confidence=1.0,
            file_path="main.py",
            line_start=6,
            line_end=6,
            symbol=None,
            evidence="FIXME: This is inefficient",
            message="FIXME comment found",
            suggestion="Fix the identified issue",
            debt_points=3,
            remediation_effort="1 hour",
            analyzer="comment_markers",
            metadata={"marker_type": "FIXME", "content": "This is inefficient"},
        ),
        Finding(
            id="finding_003",
            rule_id="comment:hack",
            category=FindingCategory.MAINTAINABILITY,
            severity=FindingSeverity.WARNING,
            confidence=1.0,
            file_path="main.py",
            line_start=8,
            line_end=8,
            symbol=None,
            evidence="HACK: Temporary workaround",
            message="HACK comment found",
            suggestion="Replace hack with proper solution",
            debt_points=5,
            remediation_effort="2 hours",
            analyzer="comment_markers",
            metadata={"marker_type": "HACK", "content": "Temporary workaround"},
        ),
    ]
