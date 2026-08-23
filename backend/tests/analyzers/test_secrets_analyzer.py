"""Tests for the secrets analyzer.

Verifies that named credential patterns (AWS, GitHub, Slack, JWT)
emit ERROR-severity findings with high confidence and that the
generic high-entropy heuristic emits WARNING-severity findings.
Also pins determinism and the security gates (lockfiles, binaries,
excluded dirs, config-example filenames).
"""

from __future__ import annotations

import pytest

from app.analyzers.secrets import SecretsAnalyzer
from app.models.finding import FindingCategory, FindingSeverity

# Each entry: (filename, body, expected_rule_id_prefix, expected_severity)
NAMED_KIND_CASES: list[tuple[str, str, str, FindingSeverity]] = [
    (
        "aws.py",
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n',
        "secrets:aws_access_key_id",
        FindingSeverity.ERROR,
    ),
    (
        "gh.py",
        'token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n',
        "secrets:github_token",
        FindingSeverity.ERROR,
    ),
    (
        "slack.py",
        'SLACK = "xoxb-1234567890-1234567890123-abcdefghij"\n',
        "secrets:slack_token",
        FindingSeverity.ERROR,
    ),
    (
        "jwt.py",
        (
            'JWT = "eyJhbGciOiJIUzI1NiJ9.'
            'eyJzdWIiOiIxMjM0NTY3ODkwIn0.'
            'SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"\n'
        ),
        "secrets:jwt",
        FindingSeverity.ERROR,
    ),
    (
        "generic.py",
        'api_key = "abcdefghijklmnopqrstuvwxyz0123456789-_"\n',
        "secrets:generic_high_entropy",
        FindingSeverity.WARNING,
    ),
]


@pytest.fixture
def analyzer() -> SecretsAnalyzer:
    return SecretsAnalyzer()


@pytest.fixture
def make_repo(tmp_path):
    """Factory that writes (relative_path, content) pairs into tmp_path and returns the root."""

    def _make(files: dict[str, str]) -> "object":
        for rel, body in files.items():
            full = tmp_path / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(body, encoding="utf-8")
        return tmp_path

    return _make


class TestNamedKindDetection:
    def test_gh_token_line_triggers_both_gh_token_and_generic_heuristic(
        self, analyzer, make_repo
    ):
        # A real production line carrying a GitHub PAT literal will
        # trigger BOTH the named github_token rule AND the generic
        # high-entropy rule (the literal also looks like
        # `token = "<long-string>"`). The analyzer must report both;
        # the user-facing dedupe / filtering lives in the frontend.
        repo = make_repo(
            {"gh.py": 'token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'}
        )
        findings = analyzer.analyze(repo)
        rule_ids = {f.rule_id for f in findings}
        assert "secrets:github_token" in rule_ids
        assert "secrets:generic_high_entropy" in rule_ids
        # Both findings live on the same line and the same file.
        for f in findings:
            assert f.file_path == "gh.py"
            assert f.line_start == 1

    @pytest.mark.parametrize(
        "filename,body,rule_prefix,severity",
        NAMED_KIND_CASES,
        ids=[c[0] for c in NAMED_KIND_CASES],
    )
    def test_named_kind_emits_finding(
        self, analyzer, make_repo, filename, body, rule_prefix, severity
    ):
        repo = make_repo({filename: body})
        findings = analyzer.analyze(repo)
        # Locate the finding for this specific rule. Other rules may
        # also fire (e.g. the generic entropy heuristic on the same
        # line), but each rule must produce exactly one finding for
        # each match position.
        rule_findings = [f for f in findings if f.rule_id == rule_prefix]
        assert len(rule_findings) >= 1
        f = rule_findings[0]
        assert f.severity == severity
        assert f.category == FindingCategory.SECURITY
        assert f.analyzer == "secrets"
        assert f.confidence >= 0.70
        assert f.debt_points > 0
        assert f.file_path == filename
        assert f.line_start == 1
        # Evidence must NOT echo the live secret. Only the redacted form.
        assert body.strip().split('"')[1] not in f.evidence
        # Redaction marker must be present.
        assert "match=" in f.evidence
        assert "kind=" in f.evidence


class TestNegativeCases:
    def test_clean_repository_returns_no_findings(self, analyzer, tmp_path):
        (tmp_path / "clean.py").write_text(
            'x = 1\nname = "alice"\nlogger.info("ready")\n',
            encoding="utf-8",
        )
        assert analyzer.analyze(tmp_path) == []

    def test_short_strings_do_not_match_generic_heuristic(
        self, analyzer, tmp_path
    ):
        (tmp_path / "short.py").write_text(
            'api_key = "shorty"\ntoken = "abc"\n',
            encoding="utf-8",
        )
        assert analyzer.analyze(tmp_path) == []

    def test_comment_only_with_secret_keyword_no_match(
        self, analyzer, tmp_path
    ):
        # Mentioning the words in a docstring must NOT trigger the
        # generic heuristic; the named patterns require literal token
        # shapes, not just keyword presence.
        (tmp_path / "doc.py").write_text(
            '"""Module about api_key rotation and token refresh."""\n',
            encoding="utf-8",
        )
        findings = analyzer.analyze(tmp_path)
        assert findings == []

    def test_empty_repository_returns_empty(self, analyzer, tmp_path):
        assert analyzer.analyze(tmp_path) == []


class TestSecurityGates:
    def test_lockfile_with_secret_like_body_is_skipped(self, analyzer, tmp_path):
        (tmp_path / "package-lock.json").write_text(
            'AKIAIOSFODNN7EXAMPLE token = "abcdefghijklmnopqrstuvwxyz0123456789-_"\n',
            encoding="utf-8",
        )
        assert analyzer.analyze(tmp_path) == []

    def test_binary_file_with_secret_like_bytes_is_skipped(
        self, analyzer, tmp_path
    ):
        # .png extension gate (binary_extension), even if the body
        # would otherwise match.
        (tmp_path / "logo.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"AKIAIOSFODNN7EXAMPLE"
        )
        assert analyzer.analyze(tmp_path) == []

    def test_excluded_directory_with_secret_is_skipped(self, analyzer, tmp_path):
        (tmp_path / ".venv" / "lib.py").parent.mkdir(parents=True)
        (tmp_path / ".venv" / "lib.py").write_text(
            'AKIAIOSFODNN7EXAMPLE\n', encoding="utf-8"
        )
        assert analyzer.analyze(tmp_path) == []

    def test_config_example_files_are_skipped(self, analyzer, tmp_path):
        (tmp_path / "config.example.yaml").write_text(
            'api_key: "abcdefghijklmnopqrstuvwxyz0123456789-_"\n',
            encoding="utf-8",
        )
        (tmp_path / ".env.example").write_text(
            'TOKEN="abcdefghijklmnopqrstuvwxyz0123456789-_"\n',
            encoding="utf-8",
        )
        assert analyzer.analyze(tmp_path) == []


class TestDeterminism:
    def test_byte_identical_findings_across_repeated_scans(
        self, analyzer, make_repo
    ):
        repo = make_repo(
            {
                "a.py": 'AKIAIOSFODNN7EXAMPLE\n',
                "b.py": 'token = "abcdefghijklmnopqrstuvwxyz0123456789-_"\n',
            }
        )
        first = analyzer.analyze(repo)
        second = analyzer.analyze(repo)
        ids_1 = sorted(f.id for f in first)
        ids_2 = sorted(f.id for f in second)
        assert ids_1 == ids_2, "Finding IDs must be deterministic across scans"
        # And the byte-level payloads match too. The codebase's
        # existing determinism contract (see backend/app/services/
        # repository.py and the API serializer) strips `detected_at`
        # before comparison because its microsecond timestamp drifts
        # between scans and is not part of the analysis payload. We
        # do the same here.
        def _canonical(f) -> str:
            import json
            payload = f.model_dump()
            payload.pop("detected_at", None)
            return json.dumps(payload, sort_keys=True, default=str)

        dumped_1 = sorted(_canonical(f) for f in first)
        dumped_2 = sorted(_canonical(f) for f in second)
        assert dumped_1 == dumped_2

    def test_finding_id_stable_across_analyzer_instances(
        self, make_repo
    ):
        repo = make_repo({"a.py": 'AKIAIOSFODNN7EXAMPLE\n'})
        a = SecretsAnalyzer()
        b = SecretsAnalyzer()
        ids_a = {f.id for f in a.analyze(repo)}
        ids_b = {f.id for f in b.analyze(repo)}
        assert ids_a == ids_b

    def test_multiple_findings_per_file_have_distinct_ids(
        self, analyzer, make_repo
    ):
        body = (
            'AKIAIOSFODNN7EXAMPLE\n'
            'token = "abcdefghijklmnopqrstuvwxyz0123456789-_"\n'
            'password = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"\n'
        )
        repo = make_repo({"a.py": body})
        findings = analyzer.analyze(repo)
        ids = [f.id for f in findings]
        assert len(ids) >= 2
        assert len(set(ids)) == len(ids), "Finding IDs must be distinct"

    def test_metadata_carries_kind_and_prefix(
        self, analyzer, make_repo
    ):
        repo = make_repo({"a.py": 'AKIAIOSFODNN7EXAMPLE\n'})
        findings = analyzer.analyze(repo)
        aws = next(f for f in findings if f.metadata["kind"] == "aws_access_key_id")
        # The match_prefix is always exactly 8 characters from the
        # matched token's beginning, regardless of how long the actual
        # match is. The AKIA fixture is the canonical AWS test key
        # `AKIAIOSFODNN7EXAMPLE`; its first 8 characters are
        # `AKIAIOSF` (A-K-I-A-I-O-S-F).
        assert aws.metadata["match_prefix"] == "AKIAIOSF"
        assert len(aws.metadata["match_prefix"]) == 8
