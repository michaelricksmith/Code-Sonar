"""Tests for the security validators."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.security import (
    BINARY_EXTENSIONS,
    EXCLUDED_DIRS,
    MAX_EVIDENCE_LENGTH,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_SCAN,
    MAX_REPO_SIZE_BYTES,
    RepositoryValidationError,
    assert_within_scan_limits,
    is_binary_content,
    is_binary_extension,
    is_excluded_directory,
    is_safe_to_read,
    is_symlink,
    redact_secrets,
    truncate_evidence,
    validate_repo_path,
)


class TestValidateRepoPath:
    def test_none_raises(self):
        with pytest.raises(RepositoryValidationError):
            validate_repo_path(None)

    def test_empty_raises(self):
        with pytest.raises(RepositoryValidationError):
            validate_repo_path("   ")

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(RepositoryValidationError):
            validate_repo_path(str(tmp_path / "missing"))

    def test_file_instead_of_dir_raises(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(RepositoryValidationError):
            validate_repo_path(str(f))

    def test_valid_dir_returns_resolved(self, tmp_repo):
        resolved = validate_repo_path(str(tmp_repo))
        assert resolved.is_dir()
        assert resolved == tmp_repo.resolve()

    def test_outside_allowlist_when_enforced(self, tmp_path):
        with pytest.raises(RepositoryValidationError):
            validate_repo_path(
                str(tmp_path),
                scan_root=Path("/some/other/place"),
                enforce_root=True,
            )

    def test_outside_allowlist_allowed_when_not_enforced(self, tmp_repo):
        # Default MVP behavior: no enforcement
        assert validate_repo_path(str(tmp_repo)) == tmp_repo.resolve()


class TestIsSafeToRead:
    def test_symlink_skipped(self, tmp_repo):
        link = tmp_repo / "link.py"
        try:
            link.symlink_to(tmp_repo / "clean.py")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        assert is_safe_to_read(link, tmp_repo) is False

    def test_binary_extension_skipped(self, tmp_repo):
        assert is_safe_to_read(tmp_repo / "image.png", tmp_repo) is False

    def test_excluded_directory_skipped(self, tmp_repo):
        assert is_safe_to_read(tmp_repo / ".venv" / "lib.py", tmp_repo) is False
        assert is_safe_to_read(tmp_repo / "node_modules" / "j.js", tmp_repo) is False
        assert is_safe_to_read(tmp_repo / "build" / "out.py", tmp_repo) is False

    def test_binary_content_skipped(self, tmp_repo):
        assert is_safe_to_read(tmp_repo / "image.png", tmp_repo) is False

    def test_oversized_file_skipped(self, tmp_repo):
        big = tmp_repo / "big.py"
        big.write_text("a", encoding="utf-8")
        original = MAX_FILE_SIZE_BYTES
        try:
            import app.security as sec
            sec.MAX_FILE_SIZE_BYTES = 0
            assert is_safe_to_read(big, tmp_repo) is False
        finally:
            import app.security as sec
            sec.MAX_FILE_SIZE_BYTES = original

    def test_normal_python_file_accepted(self, tmp_repo):
        assert is_safe_to_read(tmp_repo / "clean.py", tmp_repo) is True


class TestExcludedDirectory:
    def test_recognises_known_dirs(self):
        assert is_excluded_directory(Path(".git")) is True
        assert is_excluded_directory(Path("node_modules")) is True
        assert is_excluded_directory(Path("src/node_modules/pkg")) is True
        assert is_excluded_directory(Path(".venv")) is True
        assert is_excluded_directory(Path("build")) is True

    def test_passes_normal_path(self):
        assert is_excluded_directory(Path("src/app/main.py")) is False


class TestBinaryDetection:
    def test_png_detected_by_extension(self):
        assert is_binary_extension(Path("foo.png")) is True
        assert is_binary_extension(Path("foo.py")) is False

    def test_nul_byte_in_content(self, tmp_repo):
        assert is_binary_content(tmp_repo / "image.png") is True

    def test_text_content_passes(self, tmp_repo):
        assert is_binary_content(tmp_repo / "clean.py") is False


class TestScanLimits:
    def test_file_count_cap_raises(self):
        with pytest.raises(RepositoryValidationError):
            assert_within_scan_limits(MAX_FILES_PER_SCAN + 1, 0)

    def test_repo_size_cap_raises(self):
        with pytest.raises(RepositoryValidationError):
            assert_within_scan_limits(0, MAX_REPO_SIZE_BYTES + 1)

    def test_within_limits_ok(self):
        assert_within_scan_limits(100, 1024)


class TestSecretRedaction:
    def test_long_alphanumeric_redacted(self):
        text = "token=abcdefghijklmnopqrstuvwx123456 end"
        out = redact_secrets(text)
        assert "[REDACTED]" in out
        assert "abcdefghijklmnopqrstuvwx123456" not in out

    def test_short_strings_kept(self):
        text = "x = 1  # short"
        assert redact_secrets(text) == text

    def test_empty_passthrough(self):
        assert redact_secrets("") == ""
        assert redact_secrets(None) is None


class TestEvidenceTruncation:
    def test_short_unchanged(self):
        assert truncate_evidence("hello") == "hello"

    def test_long_truncated_with_ellipsis(self):
        long = "a" * (MAX_EVIDENCE_LENGTH + 100)
        out = truncate_evidence(long)
        assert out.endswith("...")
        assert len(out) == MAX_EVIDENCE_LENGTH

    def test_none_returns_empty(self):
        assert truncate_evidence(None) == ""