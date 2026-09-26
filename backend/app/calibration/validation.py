"""Validation and canonical hashing for calibration evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

from app.calibration.contracts import (
    ARTIFACT_TYPES,
    CONTRACT_VERSION,
    FINDING_VERDICTS,
    FORBIDDEN_KEYS,
    GRADES,
    REQUIRED_FIELDS,
    SEVERITIES,
)

_CASE_ID = re.compile(r"^csb-[0-9]{3}$")
_SHA = re.compile(r"^[0-9a-fA-F]{40,64}$")
_REVIEWER_ID = re.compile(r"^reviewer-[a-z0-9][a-z0-9-]{1,30}$")


class EvidenceValidationError(ValueError):
    """Raised when evidence is incomplete, unsafe, or version-incompatible."""


def canonical_json(artifact: Mapping[str, Any]) -> bytes:
    return json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def artifact_sha256(artifact: Mapping[str, Any]) -> str:
    """Hash semantic JSON content, independent of whitespace and key order."""
    return hashlib.sha256(canonical_json(artifact)).hexdigest()


def verify_artifact_hash(artifact: Mapping[str, Any]) -> None:
    """Verify a loaded artifact whose hash covers every other field."""
    claimed = artifact.get("artifact_sha256")
    if not isinstance(claimed, str):
        raise EvidenceValidationError("artifact_sha256 is missing")
    unhashed = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    if not hmac.compare_digest(claimed, artifact_sha256(unhashed)):
        raise EvidenceValidationError("artifact_sha256 mismatch")


def validate_reviewer_id(reviewer_id: str) -> None:
    """Require a stable pseudonym rather than a name or email address."""
    if not _REVIEWER_ID.fullmatch(reviewer_id):
        raise EvidenceValidationError("reviewer_id must be a non-identifying reviewer pseudonym")


def _walk_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_KEYS:
                raise EvidenceValidationError(f"forbidden identity/source field at {path}.{key}")
            _walk_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]")


def _validate_common(artifact: Mapping[str, Any], kind: Any) -> None:
    """Validate the fields shared by every artifact type."""
    if artifact.get("contract_version") != CONTRACT_VERSION:
        raise EvidenceValidationError("unsupported contract_version")
    if kind not in ARTIFACT_TYPES:
        raise EvidenceValidationError("unsupported artifact_type")
    missing = REQUIRED_FIELDS[str(kind)] - artifact.keys()
    if missing:
        raise EvidenceValidationError(f"missing required fields: {sorted(missing)}")
    if not _CASE_ID.fullmatch(str(artifact.get("case_id", ""))):
        raise EvidenceValidationError("case_id must match csb-NNN")
    _walk_forbidden(artifact)


def _validate_repository_metadata(artifact: Mapping[str, Any]) -> None:
    if not _SHA.fullmatch(str(artifact["commit_sha"])):
        raise EvidenceValidationError("commit_sha must be a 40-64 character hexadecimal digest")


def _validate_scoring_version(
    artifact: Mapping[str, Any], expected_scoring_version: str | None
) -> None:
    if not isinstance(artifact["scoring_version"], str) or not artifact["scoring_version"]:
        raise EvidenceValidationError("scoring_version must be non-empty")
    if expected_scoring_version and artifact["scoring_version"] != expected_scoring_version:
        raise EvidenceValidationError("scoring_version mismatch")


def _validate_analyzer_execution(artifact: Mapping[str, Any]) -> list[Any]:
    statuses = artifact["analyzer_execution"]
    if not isinstance(statuses, list) or not statuses:
        raise EvidenceValidationError("analyzer_execution must be non-empty")
    if any(item.get("status") != "completed" for item in statuses if isinstance(item, Mapping)):
        raise EvidenceValidationError("incomplete analyzer execution")
    if len(statuses) != sum(isinstance(item, Mapping) for item in statuses):
        raise EvidenceValidationError("invalid analyzer execution record")
    return statuses


def _validate_analyzer_versions(artifact: Mapping[str, Any], statuses: list[Any]) -> None:
    executed = {str(item.get("analyzer", "")) for item in statuses}
    versions = artifact["analyzer_versions"]
    if not isinstance(versions, Mapping) or set(versions) != executed:
        raise EvidenceValidationError("analyzer_versions must match executed analyzers")
    if any(not isinstance(version, str) or not version for version in versions.values()):
        raise EvidenceValidationError("analyzer versions must be non-empty strings")


def _validate_frozen_scan(
    artifact: Mapping[str, Any], expected_scoring_version: str | None
) -> None:
    _validate_scoring_version(artifact, expected_scoring_version)
    statuses = _validate_analyzer_execution(artifact)
    _validate_analyzer_versions(artifact, statuses)
    if artifact["grade"] not in GRADES:
        raise EvidenceValidationError("invalid grade")


def _validate_label_grades(artifact: Mapping[str, Any]) -> None:
    if artifact["grade"] not in GRADES or not 1 <= artifact["ordinal_health"] <= 10:
        raise EvidenceValidationError("invalid grade or ordinal_health")


def _validate_reviewer(artifact: Mapping[str, Any]) -> None:
    validate_reviewer_id(str(artifact.get("reviewer_id", "")))
    confidence = artifact.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise EvidenceValidationError("confidence must be between 0 and 1")


def _validate_adjudicated_reviewers(artifact: Mapping[str, Any]) -> None:
    reviewer_ids = artifact.get("reviewer_ids")
    if (
        not isinstance(reviewer_ids, list)
        or len(set(reviewer_ids)) < 2
        or any(not _REVIEWER_ID.fullmatch(str(item)) for item in reviewer_ids)
    ):
        raise EvidenceValidationError("adjudication requires at least two reviewer pseudonyms")


def _validate_finding_review(artifact: Mapping[str, Any]) -> None:
    if artifact["verdict"] not in FINDING_VERDICTS:
        raise EvidenceValidationError("invalid finding verdict")
    if artifact["reported_severity"] not in SEVERITIES:
        raise EvidenceValidationError("invalid reported severity")
    if artifact["expert_severity"] not in SEVERITIES | {None}:
        raise EvidenceValidationError("invalid expert severity")


def validate_artifact(
    artifact: Mapping[str, Any], *, expected_scoring_version: str | None = None
) -> None:
    """Validate one v1 artifact, rejecting incomplete or version-mismatched scans."""
    kind = artifact.get("artifact_type")
    _validate_common(artifact, kind)
    if kind == "repository_metadata":
        _validate_repository_metadata(artifact)
    if kind == "frozen_scan":
        _validate_frozen_scan(artifact, expected_scoring_version)
    if kind == "expert_label":
        _validate_label_grades(artifact)
        _validate_reviewer(artifact)
    if kind == "adjudicated_label":
        _validate_label_grades(artifact)
        _validate_adjudicated_reviewers(artifact)
    if kind == "finding_review":
        _validate_reviewer(artifact)
        _validate_finding_review(artifact)
