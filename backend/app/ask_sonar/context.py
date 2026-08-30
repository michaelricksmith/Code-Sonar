"""Structured grounding context for Ask Sonar.

Deterministic scan facts are always the authority. ML prediction and historical
similarity are optional advisory evidence and are explicitly labeled as such.
"""

from __future__ import annotations

from typing import Any

from app.history import ScanRecord
from app.ml.features import extract_scan_features
from app.ml.runtime import get_prediction_model, get_similarity_index


def _top_findings(record: ScanRecord, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        record.findings,
        key=lambda finding: (
            -finding.risk,
            -finding.debt_points,
            finding.file_path,
            finding.id,
        ),
    )
    return [finding.to_dict() for finding in ordered[:limit]]


def build_grounding_context(
    record: ScanRecord,
    *,
    task: str = "debt_risk",
    top_findings_limit: int = 10,
    similar_limit: int = 3,
) -> dict[str, Any]:
    """Build one source-separated context bundle for conversational reasoning."""
    if top_findings_limit < 1:
        raise ValueError("top_findings_limit must be at least 1")
    if similar_limit < 1:
        raise ValueError("similar_limit must be at least 1")

    deterministic: dict[str, Any] = {
        "authority": "code_sonar_deterministic",
        "scan_id": record.scan_id,
        "repository_id": record.repository_id,
        "repository_path": record.repository_path,
        "scanned_at": record.scanned_at,
        "score": record.score,
        "grade": record.grade,
        "total_debt_points": record.total_debt_points,
        "finding_count": record.finding_count,
        "category_scores": dict(record.category_scores),
        "severity_distribution": dict(record.severity_distribution),
        "findings_by_category": dict(record.findings_by_category),
        "findings_source_breakdown": dict(record.findings_source_breakdown),
        "top_findings": _top_findings(record, top_findings_limit),
    }

    features = extract_scan_features(record)

    model = get_prediction_model(task)
    if model is None:
        prediction: dict[str, Any] = {
            "status": "unavailable",
            "advisory_only": True,
            "task": task,
            "reason": "no_fitted_model_loaded",
        }
    else:
        try:
            result = model.predict(features)
            prediction = {
                "status": "available",
                "advisory_only": True,
                "task": task,
                "result": result.to_dict(),
            }
        except RuntimeError as exc:
            prediction = {
                "status": "unavailable",
                "advisory_only": True,
                "task": task,
                "reason": "model_not_ready",
                "message": str(exc),
            }

    index = get_similarity_index(task)
    if index is None:
        similarity: dict[str, Any] = {
            "status": "unavailable",
            "advisory_only": True,
            "task": task,
            "reason": "similarity_index_not_loaded",
            "cases": [],
        }
    else:
        try:
            cases = index.query(
                features,
                limit=similar_limit,
                exclude_scan_id=record.scan_id,
            )
            similarity = {
                "status": "available",
                "advisory_only": True,
                "task": task,
                "cases": [case.to_dict() for case in cases],
            }
        except RuntimeError as exc:
            similarity = {
                "status": "unavailable",
                "advisory_only": True,
                "task": task,
                "reason": "similarity_index_not_ready",
                "message": str(exc),
                "cases": [],
            }

    return {
        "context_schema_version": "1.0",
        "scan_id": record.scan_id,
        "deterministic_score_unchanged": True,
        "source_policy": {
            "deterministic_is_authoritative": True,
            "ml_is_advisory": True,
            "never_infer_missing_repository_facts": True,
        },
        "deterministic": deterministic,
        "ml_prediction": prediction,
        "historical_similarity": similarity,
    }
