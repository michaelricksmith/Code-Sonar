"""Pure builders that convert scan records into versioned dataset rows."""

from __future__ import annotations

import hashlib

from app.history import ScanRecord
from app.ml.datasets.schema import DatasetRow, LabelProvenance
from app.ml.features import extract_scan_features


def _stable_row_id(repository_id: str, scan_id: str) -> str:
    payload = f"{repository_id}:{scan_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def build_scan_dataset_row(
    record: ScanRecord,
    *,
    label: LabelProvenance | None = None,
) -> DatasetRow:
    """Build one deterministic scan-level dataset row.

    Scan-level observations use the repository id as their lineage. Later
    finding/file-level datasets will use narrower lineage ids so recurrent
    findings cannot leak across train/test partitions.
    """
    return DatasetRow(
        row_id=_stable_row_id(record.repository_id, record.scan_id),
        repository_group=record.repository_id,
        lineage_id=record.repository_id,
        scan_id=record.scan_id,
        features=extract_scan_features(record),
        label=label,
    )
