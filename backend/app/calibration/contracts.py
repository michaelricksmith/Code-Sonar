"""Dependency-free data contracts for calibration artifacts.

Contracts are deliberately plain JSON dictionaries so benchmark evidence can be
reviewed without importing the application or installing validation libraries.
"""

from __future__ import annotations

from typing import Final

CONTRACT_VERSION: Final = "calibration-evidence-v1"
ARTIFACT_TYPES: Final = frozenset(
    {"repository_metadata", "frozen_scan", "expert_label", "adjudicated_label", "finding_review"}
)
GRADES: Final = frozenset({"A", "B", "C", "D", "F"})
SEVERITIES: Final = frozenset({"info", "warning", "error", "critical"})
FINDING_VERDICTS: Final = frozenset({"true_positive", "false_positive", "uncertain"})

# Required keys are intentionally small. Optional, study-specific fields remain
# allowed, while identity/source-bearing keys are rejected by validation.
REQUIRED_FIELDS: Final[dict[str, frozenset[str]]] = {
    "repository_metadata": frozenset(
        {"contract_version", "artifact_type", "case_id", "commit_sha", "strata"}
    ),
    "frozen_scan": frozenset(
        {
            "contract_version",
            "artifact_type",
            "case_id",
            "scoring_version",
            "analyzer_versions",
            "analyzer_execution",
            "score",
            "grade",
            "findings",
        }
    ),
    "expert_label": frozenset(
        {
            "contract_version",
            "artifact_type",
            "case_id",
            "reviewer_id",
            "grade",
            "ordinal_health",
            "category_ratings",
            "confidence",
        }
    ),
    "adjudicated_label": frozenset(
        {
            "contract_version",
            "artifact_type",
            "case_id",
            "reviewer_ids",
            "grade",
            "ordinal_health",
            "category_ratings",
        }
    ),
    "finding_review": frozenset(
        {
            "contract_version",
            "artifact_type",
            "case_id",
            "finding_id",
            "analyzer",
            "verdict",
            "reported_severity",
            "expert_severity",
            "reviewer_id",
            "confidence",
        }
    ),
}

FORBIDDEN_KEYS: Final = frozenset(
    {
        "repository",
        "repository_id",
        "repository_name",
        "repository_path",
        "repo_path",
        "repo_url",
        "remote_url",
        "owner",
        "organization",
        "hostname",
        "host_path",
        "source",
        "source_code",
        "snippet",
        "evidence",
        "message",
        "suggestion",
        "symbol",
        "file_path",
        "absolute_path",
        "token",
        "credential",
        "secret",
    }
)
