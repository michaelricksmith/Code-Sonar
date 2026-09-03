"""Blinded calibration-pilot packet generation and readiness checks."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.calibration.contracts import CONTRACT_VERSION, REVIEW_PACKET_VERSION
from app.calibration.validation import (
    EvidenceValidationError,
    validate_artifact,
    validate_reviewer_id,
    verify_artifact_hash,
)


def validate_pilot_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate corpus metadata without implying that labels or accuracy exist."""
    if manifest.get("contract_version") != CONTRACT_VERSION:
        raise EvidenceValidationError("incompatible contract_version")
    if not isinstance(manifest.get("benchmark_version"), str) or not manifest["benchmark_version"]:
        raise EvidenceValidationError("benchmark_version is required")
    if not isinstance(manifest.get("scoring_version"), str) or not manifest["scoring_version"]:
        raise EvidenceValidationError("scoring_version is required")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) < 1:
        raise EvidenceValidationError("at least one case is required")
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise EvidenceValidationError("each case must be an object")
        metadata = case.get("metadata")
        if not isinstance(metadata, Mapping):
            raise EvidenceValidationError("each case requires inline repository metadata")
        validate_artifact(metadata)
        if len(set(str(metadata["commit_sha"]))) == 1:
            raise EvidenceValidationError(
                "commit_sha must be a real pinned commit, not a placeholder"
            )
        case_id = str(metadata["case_id"])
        if case_id in case_ids:
            raise EvidenceValidationError("case_id values must be unique")
        case_ids.add(case_id)
        strata = metadata.get("strata")
        if not isinstance(strata, Mapping) or any(
            not isinstance(strata.get(key), str) or not strata[key].strip()
            for key in ("size", "shape", "profile")
        ):
            raise EvidenceValidationError("strata require non-empty size, shape, and profile")
        if any(
            "replace" in str(value).lower() or "placeholder" in str(value).lower()
            for value in strata.values()
        ):
            raise EvidenceValidationError("strata placeholders must be replaced")
        if case.get("scan_file") is not None and not isinstance(case["scan_file"], str):
            raise EvidenceValidationError("scan_file must be a relative path")


def stratified_finding_sample(
    findings: Sequence[Mapping[str, Any]], *, per_cell: int = 2
) -> list[dict[str, Any]]:
    """Select deterministic samples from every analyzer/severity cell.

    Stable SHA-256 ordering prevents cherry-picking. Every non-empty cell receives
    up to ``per_cell`` findings; duplicates are impossible because cells are disjoint.
    """
    if per_cell < 1:
        raise ValueError("per_cell must be positive")
    cells: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for finding in findings:
        cells[(str(finding.get("analyzer", "")), str(finding.get("severity", "")))].append(finding)
    selected: list[dict[str, Any]] = []
    for cell in sorted(cells):
        ranked = sorted(
            cells[cell],
            key=lambda item: hashlib.sha256(str(item.get("id", "")).encode()).hexdigest(),
        )
        selected.extend(dict(item) for item in ranked[:per_cell])
    return selected


def make_review_packet(
    metadata: Mapping[str, Any], scan: Mapping[str, Any], *, reviewer_id: str, per_cell: int = 2
) -> dict[str, Any]:
    """Build a score-blinded packet containing label forms and sampled findings."""
    validate_artifact(metadata)
    validate_artifact(scan, expected_scoring_version=str(scan.get("scoring_version", "")))
    verify_artifact_hash(scan)
    if metadata["case_id"] != scan["case_id"]:
        raise EvidenceValidationError("metadata and scan case_id mismatch")
    validate_reviewer_id(reviewer_id)
    samples = stratified_finding_sample(scan["findings"], per_cell=per_cell)
    finding_forms = [
        {
            "contract_version": CONTRACT_VERSION,
            "artifact_type": "finding_review",
            "case_id": scan["case_id"],
            "finding_id": item["id"],
            "analyzer": item["analyzer"],
            "reported_severity": item["severity"],
            "verdict": None,
            "expert_severity": None,
            "reviewer_id": reviewer_id,
            "confidence": None,
            "insufficient_evidence": None,
            "rationale": None,
        }
        for item in samples
    ]
    return {
        "packet_version": REVIEW_PACKET_VERSION,
        "contract_version": CONTRACT_VERSION,
        "benchmark_version": None,
        "case_id": scan["case_id"],
        "reviewer_id": reviewer_id,
        "blinding": {"score_hidden": True, "grade_hidden": True, "other_reviews_hidden": True},
        "repository": {"commit_sha": metadata["commit_sha"], "strata": metadata["strata"]},
        "repository_label": {
            "contract_version": CONTRACT_VERSION,
            "artifact_type": "expert_label",
            "case_id": scan["case_id"],
            "reviewer_id": reviewer_id,
            "grade": None,
            "ordinal_health": None,
            "category_ratings": {},
            "confidence": None,
            "insufficient_evidence": None,
            "rationale": None,
            "status": "draft",
        },
        "finding_reviews": finding_forms,
    }


def load_finalized_independent_labels(
    manifest: Mapping[str, Any], label_documents: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Return evaluator cases only when every case has independent finalized labels."""
    validate_pilot_manifest(manifest)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for label in label_documents:
        if label.get("artifact_type") != "expert_label":
            continue
        if label.get("status") != "finalized" or label.get("insufficient_evidence") is True:
            continue
        validate_artifact(label)
        grouped[str(label["case_id"])].append(label)
    assembled = []
    for case in manifest["cases"]:
        case_id = str(case["metadata"]["case_id"])
        labels = grouped[case_id]
        reviewers = {str(label["reviewer_id"]) for label in labels}
        if len(reviewers) < 2:
            raise EvidenceValidationError(
                f"{case_id} requires at least two finalized independent expert labels; "
                "accuracy evaluation refused"
            )
        adjudicated = case.get("adjudicated_label")
        if not isinstance(adjudicated, Mapping):
            raise EvidenceValidationError(
                f"{case_id} requires finalized adjudication preserving reviewer disagreement; "
                "accuracy evaluation refused"
            )
        validate_artifact(adjudicated)
        disagreement = adjudicated.get("disagreement")
        if (
            adjudicated.get("status") != "finalized"
            or not isinstance(disagreement, Mapping)
            or not disagreement.get("resolution_rationale")
        ):
            raise EvidenceValidationError(
                "adjudication must be finalized and preserve disagreement"
            )
        scan = case.get("scan")
        if not isinstance(scan, Mapping):
            raise EvidenceValidationError("validated in-memory scan is required for evaluation")
        assembled.append(
            {
                "case_id": case_id,
                "actual_grade": scan["grade"],
                "expert_grade": adjudicated["grade"],
                "expert_ordinal_health": adjudicated["ordinal_health"],
                "strata": case["metadata"]["strata"],
            }
        )
    return assembled


def make_adjudication_packet(labels: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Create a blank adjudication form that retains each independent opinion."""
    finalized = [label for label in labels if label.get("status") == "finalized"]
    if len({str(label.get("reviewer_id")) for label in finalized}) < 2:
        raise EvidenceValidationError("adjudication requires two finalized independent reviews")
    for label in finalized:
        validate_artifact(label)
    case_ids = {str(label["case_id"]) for label in finalized}
    if len(case_ids) != 1:
        raise EvidenceValidationError("adjudication labels must describe one case")
    opinions = [
        {
            "reviewer_id": label["reviewer_id"],
            "grade": label["grade"],
            "ordinal_health": label["ordinal_health"],
            "category_ratings": label["category_ratings"],
            "confidence": label["confidence"],
        }
        for label in sorted(finalized, key=lambda item: str(item["reviewer_id"]))
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "artifact_type": "adjudicated_label",
        "case_id": next(iter(case_ids)),
        "reviewer_ids": [item["reviewer_id"] for item in opinions],
        "independent_opinions": opinions,
        "disagreement": {
            "grades": sorted({str(item["grade"]) for item in opinions}),
            "ordinal_health": [item["ordinal_health"] for item in opinions],
            "resolution_rationale": None,
        },
        "grade": None,
        "ordinal_health": None,
        "category_ratings": {},
        "status": "draft",
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
