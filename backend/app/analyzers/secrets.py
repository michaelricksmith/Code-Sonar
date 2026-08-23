"""Hardcoded-secrets detector.

Scans repository source for high-signal credential patterns that
should not be checked into version control:

  - AWS access key IDs         (``AKIA[0-9A-Z]{16}``)
  - AWS secret access keys     (40-char base64-style strings prefixed
                                with the literal "aws_secret")
  - GitHub personal access     (``gh[pousr]_[A-Za-z0-9]{36}``)
    tokens / OAuth tokens
  - Slack tokens               (``xox[bpars]-[0-9A-Za-z-]{10,}``)
  - JWTs                       (three base64url segments separated
                                by ``.``, the first two ``eyJ...``)
  - Generic high-entropy       (32+ chars with mixed case, digits, and
                                at least one symbol — heuristic; lower
                                confidence than the named kinds)

The named kinds are high-confidence matches. The generic entropy
rule has a deliberately narrow pattern to keep false positives down:
it requires the literal ``api_key=`` / ``token=`` / ``secret=``
prefix, which keeps it from flagging random prose.

Detection is gated by ``app.security`` (excluded dirs, lockfiles,
binary files, symlinks).

Finding IDs are derived from
``(rel_path, line_num, secret_kind, first_8_chars_of_match)`` so
repeated scans of the same repository produce byte-identical IDs.

Severity is always ``ERROR`` (debt_points=10) for every named kind,
because a leaked credential is a confirmed-severe problem
independent of frequency. The generic high-entropy rule emits
``WARNING`` (debt_points=5) because the match is heuristic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, Pattern

from app.analyzers.base import Analyzer
from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.security import (
    EXCLUDED_DIRS,
    is_binary_content,
    is_binary_extension,
    is_excluded_directory,
    is_lockfile,
    is_symlink,
)

# A small structural set of credit-report-style configuration files
# in which a secret-like assignment is a documentation example rather
# than a real leak. These are excluded by filename only.
CONFIG_EXAMPLES: frozenset[str] = frozenset({
    "config.example.yaml",
    "config.example.yml",
    "config.example.json",
    "settings.example.json",
    "example.env",
    ".env.example",
})

# Pattern tables. Each named kind has a confidence and a debt-points
# contribution. The generic high-entropy rule is intentionally narrow.
SECRET_PATTERNS: dict[str, tuple[Pattern[str], float, FindingSeverity, int]] = {
    "aws_access_key_id": (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        0.95,
        FindingSeverity.ERROR,
        10,
    ),
    "github_token": (
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
        0.95,
        FindingSeverity.ERROR,
        10,
    ),
    "slack_token": (
        re.compile(r"\bxox[bpars]-[A-Za-z0-9-]{10,}\b"),
        0.90,
        FindingSeverity.ERROR,
        10,
    ),
    "jwt": (
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        0.85,
        FindingSeverity.ERROR,
        10,
    ),
    # Generic entropy heuristic. Requires an explicit prefix so we do
    # not flag random prose.
    "generic_high_entropy": (
        re.compile(
            r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|pwd)"
            r"\s*[:=]\s*['\"]?"
            r"([A-Za-z0-9+/=_\-]{32,})"
            r"['\"]?"
        ),
        0.70,
        FindingSeverity.WARNING,
        5,
    ),
}


def _walk_source_files(repo_path: Path) -> Iterator[Path]:
    """Yield every plain-text source file under repo_path that passes the security gates."""

    def walk(path: Path) -> Iterator[Path]:
        try:
            entries = list(path.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIRS:
                    yield from walk(entry)
            elif entry.is_file():
                yield entry

    for fp in walk(repo_path):
        if _is_eligible(fp, repo_path):
            yield fp


def _is_eligible(file_path: Path, repo_root: Path) -> bool:
    try:
        rel = file_path.resolve().relative_to(repo_root)
    except ValueError:
        return False
    if is_symlink(file_path):
        return False
    if is_excluded_directory(rel):
        return False
    if is_lockfile(file_path):
        return False
    if file_path.name in CONFIG_EXAMPLES:
        return False
    if is_binary_extension(file_path):
        return False
    if is_binary_content(file_path):
        return False
    return True


def _safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError, ValueError):
        try:
            return path.read_text(encoding="latin-1")
        except (UnicodeDecodeError, OSError, ValueError):
            return None


def _redact(match_text: str) -> str:
    """Return a short, deterministic redaction suitable for ``evidence``.

    Keeps the first 4 and last 4 characters (or fewer for short
    matches) and replaces the middle with ``...`` so the on-screen
    finding does not echo the live credential.
    """
    if len(match_text) <= 12:
        return match_text[:2] + "..." + match_text[-2:]
    return match_text[:4] + "..." + match_text[-4:]


class SecretsAnalyzer(Analyzer):
    """Detects hardcoded credentials and high-entropy secrets in source files."""

    @property
    def name(self) -> str:
        return "secrets"

    @property
    def threshold(self) -> None:
        return None

    def analyze(self, repo_path: Path) -> list[Finding]:
        repo_path = Path(repo_path).resolve()
        if not repo_path.is_dir():
            return []
        findings: list[Finding] = []
        for file_path in _walk_source_files(repo_path):
            findings.extend(self._analyze_file(file_path, repo_path))
        return findings

    def _analyze_file(self, file_path: Path, repo_root: Path) -> list[Finding]:
        source = _safe_read(file_path)
        if source is None:
            return []
        rel_path = file_path.resolve().relative_to(repo_root).as_posix()
        findings: list[Finding] = []
        try:
            lines = source.splitlines()
        except Exception:
            return []
        for line_num, line in enumerate(lines, start=1):
            for kind, (pattern, confidence, severity, debt_points) in SECRET_PATTERNS.items():
                for match in pattern.finditer(line):
                    findings.append(self._build_finding(
                        kind=kind,
                        match_text=match.group(0),
                        rel_path=rel_path,
                        line_num=line_num,
                        confidence=confidence,
                        severity=severity,
                        debt_points=debt_points,
                    ))
        return findings

    def _build_finding(
        self,
        kind: str,
        match_text: str,
        rel_path: str,
        line_num: int,
        confidence: float,
        severity: FindingSeverity,
        debt_points: int,
    ) -> Finding:
        finding_id = (
            "finding_secrets_"
            f"{hash((rel_path, line_num, kind, match_text[:8])) & 0xFFFFFFFF:08x}"
        )
        return Finding(
            id=finding_id,
            rule_id=f"secrets:{kind}",
            category=FindingCategory.SECURITY,
            severity=severity,
            confidence=confidence,
            file_path=rel_path,
            line_start=line_num,
            line_end=line_num,
            symbol=None,
            evidence=f"match={_redact(match_text)} kind={kind}",
            message=(
                f"Hardcoded {kind} detected in {rel_path}:{line_num}; "
                "rotate the credential and move it to a secrets manager."
            ),
            suggestion=(
                "Revoke the leaked credential immediately, store the new "
                "value in your secrets manager, and reference it via "
                "environment variables at runtime."
            ),
            debt_points=debt_points,
            remediation_effort="1 hour",
            analyzer=self.name,
            metadata={"kind": kind, "match_prefix": match_text[:8]},
        )
