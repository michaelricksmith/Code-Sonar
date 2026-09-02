"""Create privacy-safe frozen scan evidence from an authoritative API response."""

from __future__ import annotations

from typing import Any

from app.calibration.contracts import CONTRACT_VERSION
from app.calibration.validation import artifact_sha256, validate_artifact

_SAFE_FINDING_KEYS = {
    "id",
    "rule_id",
    "category",
    "severity",
    "confidence",
    "debt_points",
    "analyzer",
}


def capture_frozen_scan(
    scan: dict[str, Any],
    *,
    case_id: str,
    analyzer_versions: dict[str, str],
    expected_scoring_version: str,
) -> dict[str, Any]:
    """Reduce a complete scan to derived facts; never preserve source evidence or identity."""
    safe_findings = [
        {key: finding[key] for key in sorted(_SAFE_FINDING_KEYS) if key in finding}
        for finding in scan.get("findings", [])
    ]
    artifact: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "artifact_type": "frozen_scan",
        "case_id": case_id,
        "scoring_version": scan.get("scoring_version"),
        "analyzer_versions": dict(sorted(analyzer_versions.items())),
        "analyzer_execution": scan.get("analyzer_execution", []),
        "score": scan.get("score"),
        "grade": scan.get("grade"),
        "category_scores": scan.get("category_scores", {}),
        "total_debt_points": scan.get("total_debt_points"),
        "findings": safe_findings,
    }
    validate_artifact(artifact, expected_scoring_version=expected_scoring_version)
    return {**artifact, "artifact_sha256": artifact_sha256(artifact)}
