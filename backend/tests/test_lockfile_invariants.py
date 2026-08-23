"""Lockfile exclusion invariants.

These regression tests guarantee that filename-specific lockfiles
never trigger source-code maintainability debt. They pin the
behaviour so future analyzers cannot regress to scanning lockfiles
or other generated dependency-metadata files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analyzers.comment_markers import CommentMarkersAnalyzer
from app.analyzers.cyclomatic_complexity import CyclomaticComplexityAnalyzer
from app.analyzers.nesting_depth import NestingDepthAnalyzer
from app.analyzers.oversized_files import OversizedFilesAnalyzer
from app.security import (
    LOCKFILE_NAMES,
    is_binary_extension,
    is_lockfile,
)
from app.services.repository import scan_repository


class TestLockfileConstant:
    def test_required_lockfile_names_present(self):
        required = {
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "Pipfile.lock",
        }
        missing = required - LOCKFILE_NAMES
        assert not missing, f"Missing lockfile names: {missing}"

    def test_legitimate_json_yaml_not_lockfiles(self):
        # The exclusion is filename-specific; ordinary JSON/YAML config
        # files must remain analyzable.
        assert "package.json" not in LOCKFILE_NAMES
        assert "tsconfig.json" not in LOCKFILE_NAMES
        assert "config.yaml" not in LOCKFILE_NAMES
        assert "config.yml" not in LOCKFILE_NAMES


class TestIsLockfile:
    @pytest.mark.parametrize("name", [
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Pipfile.lock",
        "composer.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "uv.lock",
        "pdm.lock",
        "npm-shrinkwrap.json",
    ])
    def test_recognises_lockfiles(self, name):
        assert is_lockfile(Path(name)) is True

    @pytest.mark.parametrize("name", [
        "package.json",
        "tsconfig.json",
        "config.yaml",
        "config.yml",
        "settings.json",
        ".eslintrc.json",
        "package-lock.json.bak",
        "mypackage-lock.json",
    ])
    def test_does_not_recognise_non_lockfiles(self, name):
        assert is_lockfile(Path(name)) is False


class TestAnalyzersSkipLockfiles:
    @pytest.mark.parametrize("analyzer_cls", [
        OversizedFilesAnalyzer,
        CyclomaticComplexityAnalyzer,
        NestingDepthAnalyzer,
    ])
    def test_python_bodied_lockfile_skipped(self, tmp_path, analyzer_cls):
        # Build a Pipfile.lock whose body looks like Python and would
        # otherwise trigger an AST/line-count analysis. Filename gate
        # must prevent this.
        (tmp_path / "Pipfile.lock").write_text(
            "def f(x):\n" * 50 + "    pass\n" * 200,
            encoding="utf-8",
        )
        analyzer = analyzer_cls()
        assert analyzer.analyze(tmp_path) == []

    def test_oversized_files_skips_lockfiles(self, tmp_path):
        (tmp_path / "package-lock.json").write_text(
            "\n".join(f'"k{i}": "v"' for i in range(2000)),
            encoding="utf-8",
        )
        # Ordinary package.json still analyzable.
        (tmp_path / "package.json").write_text(
            "\n".join(f'"k{i}": "v"' for i in range(2000)),
            encoding="utf-8",
        )
        analyzer = OversizedFilesAnalyzer()
        findings = analyzer.analyze(tmp_path)
        paths = {f.file_path for f in findings}
        assert "package-lock.json" not in paths
        assert "package.json" in paths

    def test_comment_markers_skips_lockfiles(self, tmp_path):
        (tmp_path / "yarn.lock").write_text(
            "# TODO: this should not surface\n" * 100,
            encoding="utf-8",
        )
        # Plain .md or .yaml file with TODO markers still analyzable.
        (tmp_path / "notes.md").write_text(
            "# TODO: ship\n" * 5, encoding="utf-8"
        )
        analyzer = CommentMarkersAnalyzer()
        findings = analyzer.analyze(tmp_path)
        paths = {f.file_path for f in findings}
        assert "yarn.lock" not in paths
        assert "notes.md" in paths

    def test_full_pipeline_excludes_lockfiles(self, tmp_path):
        (tmp_path / "Pipfile.lock").write_text(
            "def f():\n    pass\n", encoding="utf-8"
        )
        # NOTE: avoid directory named `tests/` because Windows treats
        # `tests` as a reserved shell directory in some contexts and
        # raises PermissionError on write.
        test_dir = tmp_path / "test_pkg"
        test_dir.mkdir()
        (test_dir / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        findings = scan_repository(tmp_path)
        assert all("Pipfile.lock" not in f.file_path for f in findings)


class TestBinaryExtensionStillHonored:
    def test_binary_extensions_unchanged(self):
        # Lockfile exclusion must not regress the binary-extension gate.
        assert is_binary_extension(Path("foo.png")) is True
        assert is_binary_extension(Path("foo.py")) is False
