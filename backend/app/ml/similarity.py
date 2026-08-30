"""Historical scan similarity index for KNN-style institutional memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from app.ml.datasets import DatasetRow
from app.ml.features import FEATURE_SCHEMA_VERSION, ScanFeatureVector


@dataclass(frozen=True, slots=True)
class SimilarCase:
    """One historical scan nearest to a query feature vector."""

    scan_id: str
    row_id: str
    repository_group: str
    lineage_id: str
    distance: float
    label_value: str | None
    label_trust_tier: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "row_id": self.row_id,
            "repository_group": self.repository_group,
            "lineage_id": self.lineage_id,
            "distance": self.distance,
            "label_value": self.label_value,
            "label_trust_tier": self.label_trust_tier,
        }


class SimilarityIndex:
    """Scaled nearest-neighbor index over version-compatible dataset rows."""

    def __init__(self) -> None:
        self._rows: list[DatasetRow] = []
        self._scaler: StandardScaler | None = None
        self._neighbors: NearestNeighbors | None = None

    @property
    def size(self) -> int:
        return len(self._rows)

    def fit(self, rows: list[DatasetRow]) -> None:
        """Build an index from rows using the current feature schema only."""
        if not rows:
            raise ValueError("At least one dataset row is required")
        for row in rows:
            if row.feature_schema_version != FEATURE_SCHEMA_VERSION:
                raise ValueError("Incompatible feature schema version")

        ordered = sorted(rows, key=lambda row: (row.scan_id, row.row_id))
        matrix = [list(row.features.ordered_values()) for row in ordered]
        scaler = StandardScaler()
        scaled = scaler.fit_transform(matrix)
        neighbors = NearestNeighbors(metric="euclidean")
        neighbors.fit(scaled)

        self._rows = ordered
        self._scaler = scaler
        self._neighbors = neighbors

    def query(
        self,
        features: ScanFeatureVector,
        *,
        limit: int = 5,
        exclude_scan_id: str | None = None,
    ) -> tuple[SimilarCase, ...]:
        """Return nearest historical cases in deterministic distance order."""
        if self._scaler is None or self._neighbors is None or not self._rows:
            raise RuntimeError("Similarity index must be fitted before query")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        requested = min(len(self._rows), limit + (1 if exclude_scan_id else 0))
        vector = self._scaler.transform([list(features.ordered_values())])
        distances, indices = self._neighbors.kneighbors(vector, n_neighbors=requested)

        cases: list[SimilarCase] = []
        for distance, index in zip(distances[0], indices[0], strict=True):
            row = self._rows[int(index)]
            if exclude_scan_id is not None and row.scan_id == exclude_scan_id:
                continue
            label = row.label
            cases.append(
                SimilarCase(
                    scan_id=row.scan_id,
                    row_id=row.row_id,
                    repository_group=row.repository_group,
                    lineage_id=row.lineage_id,
                    distance=float(distance),
                    label_value=None if label is None else label.value,
                    label_trust_tier=(
                        None if label is None else label.trust_tier.value
                    ),
                )
            )
            if len(cases) >= limit:
                break

        return tuple(
            sorted(cases, key=lambda case: (case.distance, case.scan_id, case.row_id))
        )
