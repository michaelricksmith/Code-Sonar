"""Risk Hotspots — Phase 1 of Fastest-Route-to-Private-Beta.

Code Sonar reports uncomfortable results when the evidence supports
them. Hotspots make that evidence actionable: which files are
carrying the most risk, and why?

Deterministic, explainable, simple — no arbitrary score tuning, no
git/churn/ownership, no new infrastructure. Pure function over the
already-collected scan data.

Public surface:
- ``compute_hotspots(findings, top_n=10)`` → ``HotspotResult``
- ``HotspotResult.to_dict()`` → JSON-serializable dict

Scoring formula (deterministic, no arbitrary tuning):

    hotspot_score = debt_total
                  + severity_max_weight
                  + finding_count
                  + analyzer_diversity * 2

where:
- debt_total = sum of ``finding.debt_points`` for all findings on the file
- severity_max_weight = max(SEV_WEIGHT) over all findings on the file
  (SEV_WEIGHT = {info: 1, warning: 2, error: 3, critical: 4} —
   identical to the drift engine risk proxy)
- finding_count = number of findings on the file
- analyzer_diversity = number of distinct ``analyzer`` values

The additional signals (complexity, size, nesting) are computed
from analyzer metadata when present and reported in the per-file
``breakdown`` for explainability, but do not contribute to the
top-line score. This keeps the score formula simple, predictable,
and aligned with what the user sees.

Why this shape?
- ``debt_total`` is the dominant signal — it already encodes severity
  weighting, source-context modifier, and confidence modifier via the
  scoring engine. A file with $X of debt points is genuinely $X worse
  than a file with no debt points.
- ``severity_max_weight`` surfaces files with even a single critical
  finding — even if the rest are clean.
- ``finding_count`` rewards files where many small problems compound.
- ``analyzer_diversity`` rewards files where multiple analyzers
  flag the same code — a stronger signal than any single analyzer.

Ordering: descending by hotspot_score, then by file_path
(tie-breaker) — deterministic, ordering-independent.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.models.finding import Finding, FindingSeverity

# Mirror the drift engine risk proxy exactly so hotspot scores and
# drift classifications share the same severity semantics.
SEVERITY_WEIGHT: dict[str, int] = {
    "info": 1,
    "warning": 2,
    "error": 3,
    "critical": 4,
}

# Per-analyzer metadata keys the explainability breakdown looks at.
# These are *additional* signals (do not contribute to the top-line
# score); they appear in the per-file ``breakdown`` so the user can
# see *why* a file is hot.
METADATA_COMPLEXITY_KEYS = ("cc", "cyclomatic_complexity")
METADATA_SIZE_KEYS = ("loc", "lines", "length", "size")
METADATA_NESTING_KEYS = ("max_depth", "nesting_depth")


class Hotspot:
    """A single ranked risk hotspot (one file).

    ``score`` is the top-line risk number. ``breakdown`` is the
    human-readable explanation: every component that contributed to
    the score plus the optional metadata-derived signals
    (complexity, size, nesting).
    """

    __slots__ = (
        "file_path",
        "score",
        "debt_total",
        "finding_count",
        "severity_max",
        "severity_max_weight",
        "analyzer_diversity",
        "analyzer_breakdown",
        "severity_breakdown",
        "category_breakdown",
        "complexity_max",
        "size_max",
        "nesting_max",
        "contributing_finding_ids",
    )

    def __init__(
        self,
        file_path: str,
        score: int,
        debt_total: int,
        finding_count: int,
        severity_max: str,
        severity_max_weight: int,
        analyzer_diversity: int,
        analyzer_breakdown: dict[str, int],
        severity_breakdown: dict[str, int],
        category_breakdown: dict[str, int],
        complexity_max: int,
        size_max: int,
        nesting_max: int,
        contributing_finding_ids: list[str],
    ) -> None:
        self.file_path = file_path
        self.score = score
        self.debt_total = debt_total
        self.finding_count = finding_count
        self.severity_max = severity_max
        self.severity_max_weight = severity_max_weight
        self.analyzer_diversity = analyzer_diversity
        self.analyzer_breakdown = analyzer_breakdown
        self.severity_breakdown = severity_breakdown
        self.category_breakdown = category_breakdown
        self.complexity_max = complexity_max
        self.size_max = size_max
        self.nesting_max = nesting_max
        self.contributing_finding_ids = contributing_finding_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "score": self.score,
            "debt_total": self.debt_total,
            "finding_count": self.finding_count,
            "severity_max": self.severity_max,
            "severity_max_weight": self.severity_max_weight,
            "analyzer_diversity": self.analyzer_diversity,
            "analyzer_breakdown": dict(self.analyzer_breakdown),
            "severity_breakdown": dict(self.severity_breakdown),
            "category_breakdown": dict(self.category_breakdown),
            "complexity_max": self.complexity_max,
            "size_max": self.size_max,
            "nesting_max": self.nesting_max,
            "contributing_finding_ids": list(self.contributing_finding_ids),
        }


class HotspotResult:
    """The full ranked-hotspots result for one scan.

    ``hotspots`` is sorted by ``(score DESC, file_path ASC)`` so the
    output is deterministic regardless of input ordering. ``total_files``
    is the count of distinct files in the scan, regardless of how many
    have findings.
    """

    __slots__ = (
        "hotspots",
        "total_files",
        "files_with_findings",
        "total_findings",
        "total_debt",
    )

    def __init__(
        self,
        hotspots: list[Hotspot],
        total_files: int,
        files_with_findings: int,
        total_findings: int,
        total_debt: int,
    ) -> None:
        self.hotspots = hotspots
        self.total_files = total_files
        self.files_with_findings = files_with_findings
        self.total_findings = total_findings
        self.total_debt = total_debt

    def to_dict(self) -> dict[str, Any]:
        return {
            "hotspots": [h.to_dict() for h in self.hotspots],
            "total_files": self.total_files,
            "files_with_findings": self.files_with_findings,
            "total_findings": self.total_findings,
            "total_debt": self.total_debt,
        }


def _severity_value(s: str | FindingSeverity) -> tuple[str, int]:
    """Return ``(severity_string, weight)`` with safe fallback."""
    sv = s.value if isinstance(s, FindingSeverity) else str(s)
    return sv, SEVERITY_WEIGHT.get(sv, 1)


def _extract_metadata_max(
    findings_for_file: list[Finding],
    keys: tuple[str, ...],
) -> int:
    """Return the maximum integer value across ``keys`` in any
    finding's ``metadata`` dict. Returns 0 when none of the keys are
    present in any finding on the file.
    """
    best = 0
    for f in findings_for_file:
        for k in keys:
            v = f.metadata.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if int(v) > best:
                    best = int(v)
    return best


def _build_hotspot_for_file(file_path: str, file_findings: list[Finding]) -> Hotspot:
    """Compute the hotspot record for one file.

    Input: findings for one file (already filtered by ``file_path``).
    Output: a populated ``Hotspot`` with score + breakdown.
    """
    debt_total = sum(f.debt_points for f in file_findings)
    finding_count = len(file_findings)

    # Severity: track the highest-weight severity on the file.
    severity_max = "info"
    severity_max_weight = 1
    severity_breakdown: Counter[str] = Counter()
    for f in file_findings:
        sv, w = _severity_value(f.severity)
        severity_breakdown[sv] += 1
        if w > severity_max_weight:
            severity_max = sv
            severity_max_weight = w

    analyzer_breakdown: Counter[str] = Counter(f.analyzer for f in file_findings)
    analyzer_diversity = len(analyzer_breakdown)
    category_breakdown = Counter(
        f.category.value for f in file_findings
    )

    complexity_max = _extract_metadata_max(file_findings, METADATA_COMPLEXITY_KEYS)
    size_max = _extract_metadata_max(file_findings, METADATA_SIZE_KEYS)
    nesting_max = _extract_metadata_max(file_findings, METADATA_NESTING_KEYS)

    contributing_finding_ids = sorted(f.id for f in file_findings)

    score = debt_total + severity_max_weight + finding_count + analyzer_diversity * 2

    return Hotspot(
        file_path=file_path,
        score=score,
        debt_total=debt_total,
        finding_count=finding_count,
        severity_max=severity_max,
        severity_max_weight=severity_max_weight,
        analyzer_diversity=analyzer_diversity,
        analyzer_breakdown=dict(analyzer_breakdown),
        severity_breakdown=dict(severity_breakdown),
        category_breakdown=dict(category_breakdown),
        complexity_max=complexity_max,
        size_max=size_max,
        nesting_max=nesting_max,
        contributing_finding_ids=contributing_finding_ids,
    )


def compute_hotspots(
    findings: Iterable[Finding],
    *,
    top_n: int = 10,
) -> HotspotResult:
    """Compute ranked risk hotspots from a list of findings.

    Pure function of the input. Deterministic:
    - output ordering is descending by score, then ascending by file_path
    - input ordering does not affect output (we group by file_path
      before classifying)

    Args:
        findings: iterable of Finding objects from a single scan.
        top_n: how many top hotspots to return in ``hotspots``.
            The default of 10 keeps the dashboard response small;
            pass a larger value for full rankings.

    Returns:
        ``HotspotResult`` with the top-N ranked hotspots plus
        scan-level aggregates. ``total_files`` includes files that
        have NO findings (we count via the ``file_path`` set across
        all findings only, so we cannot distinguish "file with 0
        findings" from "file we never scanned"; the API layer is
        responsible for the former).
    """
    findings_list = list(findings)
    by_file: dict[str, list[Finding]] = {}
    for f in findings_list:
        by_file.setdefault(f.file_path, []).append(f)

    hotspots = [_build_hotspot_for_file(fp, fs) for fp, fs in by_file.items()]
    # Deterministic ordering: descending by score, then ascending by
    # file_path as tie-breaker. Negate score for stable descending
    # sort in Python.
    hotspots.sort(key=lambda h: (-h.score, h.file_path))

    total_debt = sum(f.debt_points for f in findings_list)

    return HotspotResult(
        hotspots=hotspots[:top_n],
        total_files=len(by_file),
        files_with_findings=len(by_file),
        total_findings=len(findings_list),
        total_debt=total_debt,
    )


__all__ = [
    "Hotspot",
    "HotspotResult",
    "SEVERITY_WEIGHT",
    "compute_hotspots",
]
