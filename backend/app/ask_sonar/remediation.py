"""Grounded remediation planning for Ask Sonar.

Plans are derived only from persisted Code Sonar findings. The language model may
explain a plan conversationally, but it does not define the executable target,
instruction, risk, or approval identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, cast

from app.history import FindingSnapshot, ScanRecord

PLAN_SCHEMA_VERSION = "1.0"
RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class RemediationPlan:
    plan_id: str
    scan_id: str
    repository_id: str
    finding_id: str
    rule_id: str
    category: str
    severity: str
    file_path: str
    line_start: int | None
    line_end: int | None
    summary: str
    rationale: str
    instruction: str
    expected_files: tuple[str, ...]
    risk_level: RiskLevel
    validation_required: bool = True
    approval_required: bool = True
    expected_score_impact: None = None
    plan_schema_version: str = PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_schema_version": self.plan_schema_version,
            "plan_id": self.plan_id,
            "scan_id": self.scan_id,
            "repository_id": self.repository_id,
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "summary": self.summary,
            "rationale": self.rationale,
            "instruction": self.instruction,
            "expected_files": list(self.expected_files),
            "risk_level": self.risk_level,
            "validation_required": self.validation_required,
            "approval_required": self.approval_required,
            "expected_score_impact": self.expected_score_impact,
            "deterministic_score_authority": "code_sonar",
        }


def _risk_for_severity(severity: str) -> RiskLevel:
    value = {
        "info": "low",
        "warning": "medium",
        "error": "high",
        "critical": "critical",
    }.get(severity, "high")
    return cast(RiskLevel, value)


def _instruction_for_finding(finding: FindingSnapshot) -> str:
    suggestion = (finding.suggestion or "").strip()
    instruction = (
        f"Resolve Code Sonar finding {finding.id} ({finding.rule_id}) in "
        f"{finding.file_path}. Preserve intended behavior and make the smallest "
        "safe change necessary to address the finding."
    )
    if suggestion:
        instruction += f" Code Sonar suggestion: {suggestion}"
    instruction += " Do not modify unrelated files and do not commit, push, or merge."
    return instruction


def _plan_id(record: ScanRecord, finding: FindingSnapshot, instruction: str) -> str:
    material = "|".join(
        [
            PLAN_SCHEMA_VERSION,
            record.scan_id,
            record.repository_id,
            finding.id,
            finding.rule_id,
            finding.file_path,
            str(finding.line_start),
            str(finding.line_end),
            instruction,
        ]
    )
    return "plan-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def build_remediation_plan(record: ScanRecord, finding_id: str) -> RemediationPlan:
    """Build one deterministic execution plan from a persisted finding."""
    finding = next((item for item in record.findings if item.id == finding_id), None)
    if finding is None:
        raise LookupError("Finding was not present in the persisted scan")

    instruction = _instruction_for_finding(finding)
    return RemediationPlan(
        plan_id=_plan_id(record, finding, instruction),
        scan_id=record.scan_id,
        repository_id=record.repository_id,
        finding_id=finding.id,
        rule_id=finding.rule_id,
        category=finding.category,
        severity=finding.severity,
        file_path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        summary=finding.message,
        rationale=(
            "This plan targets an existing persisted Code Sonar finding. "
            "Any score impact is determined only after validation and deterministic rescan."
        ),
        instruction=instruction,
        expected_files=(finding.file_path,),
        risk_level=_risk_for_severity(finding.severity),
    )
