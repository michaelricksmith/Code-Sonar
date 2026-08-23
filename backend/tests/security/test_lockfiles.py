"""Tests for lockfile filtering.

Verifies that filename-specific dependency-metadata files are treated
as non-source while legitimate .json / .yaml configuration and source
files remain analyzable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analyzers.oversized_files import OversizedFilesAnalyzer
from app.security import (
    LOCKFILE_NAMES,
    is_lockfile,
)


class TestLockfileDetection:
    @pytest.mark.parametrize("name", [
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Pipfile.lock",
        "composer.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "bun.lockb",
        "uv.lock",
        "pdm.lock",
        "npm-shrinkwrap.json",
    ])
    def test_lockfiles_are_recognised(self, name):
        assert is_lockfile(Path(name)) is True

    @pytest.mark.parametrize("name", [
        "package.json",
        "tsconfig.json",
        "tsconfig.node.json",
        ".eslintrc.json",
        "manifest.json",
        "config.yaml",
        "config.yml",
        "settings.yaml",
        "pyproject.toml",
        "package-lock.json.bak",
        "mypackage-lock.json",
    ])
    def test_non_lockfile_names_are_not_recognised(self, name):
        assert is_lockfile(Path(name)) is False


class TestLockfileNotInLockfileSet:
    def test_legitimate_json_yaml_not_in_set(self):
        assert "package.json" not in LOCKFILE_NAMES
        assert "tsconfig.json" not in LOCKFILE_NAMES
        assert "config.yaml" not in LOCKFILE_NAMES
        assert "config.yml" not in LOCKFILE_NAMES


class TestOversizedFilesSkipsLockfiles:
    def test_lockfile_with_many_lines_is_skipped(self, tmp_path):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as t:
            root = Path(t)
            lock = root / "package-lock.json"
            lock.write_text("\n".join(f'"x{i}": "y"' for i in range(2000)),
                            encoding="utf-8")
            legit_json = root / "package.json"
            legit_json.write_text(
                "\n".join(f'"x{i}": "y"' for i in range(2000)),
                encoding="utf-8",
            )
            analyzer = OversizedFilesAnalyzer(threshold=500)
            findings = analyzer.analyze(root)
            paths = {f.file_path for f in findings}
            assert "package-lock.json" not in paths, (
                "package-lock.json must be excluded from source-code analysis"
            )
            assert "package.json" in paths, (
                "ordinary package.json must still be analyzable as source code"
            )

    def test_yaml_config_still_analyzed(self, tmp_path):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as t:
            root = Path(t)
            (root / "ci.yaml").write_text(
                "\n".join(f"key{i}: val{i}" for i in range(800)),
                encoding="utf-8",
            )
            (root / "pnpm-lock.yaml").write_text(
                "\n".join(f"  x{i}: y{i}" for i in range(800)),
                encoding="utf-8",
            )
            analyzer = OversizedFilesAnalyzer(threshold=500)
            findings = analyzer.analyze(root)
            paths = {f.file_path for f in findings}
            assert "ci.yaml" in paths
            assert "pnpm-lock.yaml" not in paths

    def test_dotnet_lockfile_skipped(self, tmp_path):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as t:
            root = Path(t)
            (root / "Cargo.lock").write_text(
                "\n".join(f"k{i} = v{i}" for i in range(2000)),
                encoding="utf-8",
            )
            analyzer = OversizedFilesAnalyzer(threshold=500)
            assert analyzer.analyze(root) == []
