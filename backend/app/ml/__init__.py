"""Machine-learning intelligence for Code Sonar.

This package is intentionally advisory. It consumes deterministic scan/history
outputs and must never mutate or replace the authoritative scoring engine.
"""

from app.ml.features import FEATURE_SCHEMA_VERSION, ScanFeatureVector, extract_scan_features

__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "ScanFeatureVector",
    "extract_scan_features",
]
