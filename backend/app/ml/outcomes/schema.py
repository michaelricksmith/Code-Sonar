"""Versioned remediation outcome records for higher-trust ML labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

OUTCOME_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class RemediationOutcome:
    """Observed result of one remediation attempt.

    This record captures validation facts only. It does not change the deterministic
    Code Sonar score; score/debt deltas are observations from before/after scans.
    """

    outcome_id: str
    repository_id: str
    finding_id: str
    before_scan_id: str
    after_scan_id: str
    attempted_at: str
    executor: str
    remediation_kind: str
    build_passed: bool | None
    tests_passed: bool | None
    finding_resolved: bool
    finding_reintroduced: bool = False
    regression_detected: bool = False
    score_delta: int = 0
    debt_points_delta: int = 0

    @property
    def successful(self) -> bool:
        """Return whether the observed remediation met the core success contract."""
        validations_ok = self.build_passed is not False and self.tests_passed is not False
        return (
            self.finding_resolved
            and not self.finding_reintroduced
            and not self.regression_detected
            and validations_ok
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_schema_version": OUTCOME_SCHEMA_VERSION,
            "outcome_id": self.outcome_id,
            "repository_id": self.repository_id,
            "finding_id": self.finding_id,
            "before_scan_id": self.before_scan_id,
            "after_scan_id": self.after_scan_id,
            "attempted_at": self.attempted_at,
            "executor": self.executor,
            "remediation_kind": self.remediation_kind,
            "build_passed": self.build_passed,
            "tests_passed": self.tests_passed,
            "finding_resolved": self.finding_resolved,
            "finding_reintroduced": self.finding_reintroduced,
            "regression_detected": self.regression_detected,
            "score_delta": self.score_delta,
            "debt_points_delta": self.debt_points_delta,
            "successful": self.successful,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemediationOutcome":
        version = data.get("outcome_schema_version")
        if version != OUTCOME_SCHEMA_VERSION:
            raise ValueError(f"Unsupported remediation outcome schema: {version!r}")
        return cls(
            outcome_id=str(data["outcome_id"]),
            repository_id=str(data["repository_id"]),
            finding_id=str(data["finding_id"]),
            before_scan_id=str(data["before_scan_id"]),
            after_scan_id=str(data["after_scan_id"]),
            attempted_at=str(data["attempted_at"]),
            executor=str(data["executor"]),
            remediation_kind=str(data["remediation_kind"]),
            build_passed=data.get("build_passed"),
            tests_passed=data.get("tests_passed"),
            finding_resolved=bool(data["finding_resolved"]),
            finding_reintroduced=bool(data.get("finding_reintroduced", False)),
            regression_detected=bool(data.get("regression_detected", False)),
            score_delta=int(data.get("score_delta", 0)),
            debt_points_delta=int(data.get("debt_points_delta", 0)),
        )
