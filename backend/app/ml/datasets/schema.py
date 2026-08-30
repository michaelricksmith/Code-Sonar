"""Dataset contracts for leakage-safe Code Sonar ML training rows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.ml.features import FEATURE_SCHEMA_VERSION, ScanFeatureVector

DATASET_SCHEMA_VERSION: str = "1.0"


class LabelTrustTier(str, Enum):
    """How trustworthy the target label is for supervised learning."""

    PROXY = "proxy"
    HISTORICAL_GIT = "historical_git"
    DEVELOPER_FEEDBACK = "developer_feedback"
    REMEDIATION_OUTCOME = "remediation_outcome"
    PRODUCTION_VALIDATED = "production_validated"


@dataclass(frozen=True, slots=True)
class LabelProvenance:
    """Describes where a supervised label came from."""

    task: str
    value: str
    trust_tier: LabelTrustTier
    source: str
    observed_at: str | None = None

    @property
    def is_proxy(self) -> bool:
        return self.trust_tier is LabelTrustTier.PROXY

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "value": self.value,
            "trust_tier": self.trust_tier.value,
            "source": self.source,
            "observed_at": self.observed_at,
            "is_proxy": self.is_proxy,
        }


@dataclass(frozen=True, slots=True)
class DatasetRow:
    """One versioned training/evaluation row.

    ``repository_group`` is mandatory so train/test splitters can keep repository
    groups isolated when evaluating cross-repository generalization. ``lineage_id``
    identifies related observations that must not be split across train/test when
    they describe the same evolving entity.
    """

    row_id: str
    repository_group: str
    lineage_id: str
    scan_id: str
    features: ScanFeatureVector
    label: LabelProvenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "row_id": self.row_id,
            "repository_group": self.repository_group,
            "lineage_id": self.lineage_id,
            "scan_id": self.scan_id,
            "features": self.features.to_dict()["features"],
            "label": None if self.label is None else self.label.to_dict(),
        }
