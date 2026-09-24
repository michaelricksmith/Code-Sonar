"""API and contract tests for Ask Sonar remediation planning."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.ask_sonar.remediation import build_remediation_plan
from app.ask_sonar.runtime import set_scan_provider
from app.history import ScanRecord, build_scan_record
from app.main import app
from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.scoring.engine import calculate_score


@pytest.fixture(autouse=True)
def reset_scan_provider():
    set_scan_provider(None)
    yield
    set_scan_provider(None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _record(repository_path: str = "/tmp/example-repo") -> ScanRecord:
    finding = Finding(
        id="finding-1",
        rule_id="oversized-functions:rule",
        category=FindingCategory.COMPLEXITY,
        severity=FindingSeverity.WARNING,
        confidence=0.95,
        file_path="src/service.py",
        line_start=10,
        line_end=80,
        symbol="process_request",
        evidence="safe evidence",
        message="Function is larger than the configured threshold.",
        suggestion="Split the function into smaller focused helpers.",
        debt_points=4,
        remediation_effort="1 hour",
        analyzer="oversized_functions",
        metadata={},
    )
    findings = [finding]
    return build_scan_record(
        repository_id="repo-1",
        repository_path=repository_path,
        findings=findings,
        scoring=calculate_score(findings),
        scan_id="scan-1",
        scanned_at="2026-08-30T23:00:00+00:00",
    )


@dataclass
class FakeAuthorization:
    request_id: str
    repository_path: str
    finding_id: str
    scan_id: str
    instruction: str
    remediation_kind: str


@dataclass
class FakeWorkflow:
    request: FakeAuthorization

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request.request_id,
            "completed": True,
            "active_checkout_modified": False,
            "deterministic_score_authority": "code_sonar",
        }


class CapturingOrchestrator:
    def __init__(self) -> None:
        self.requests: list[FakeAuthorization] = []

    def run_authorized(self, authorization: FakeAuthorization) -> FakeWorkflow:
        self.requests.append(authorization)
        return FakeWorkflow(authorization)


class CapturingAuthorizationService:
    def issue(self, **kwargs: str) -> FakeAuthorization:
        return FakeAuthorization(
            request_id=kwargs["request_id"],
            repository_path=kwargs["repository_path"],
            finding_id=kwargs["finding_id"],
            scan_id=kwargs["scan_id"],
            instruction=kwargs["instruction"],
            remediation_kind=kwargs["remediation_kind"],
        )


def test_plan_is_deterministic_and_does_not_predict_score_impact() -> None:
    record = _record()

    first = build_remediation_plan(record, "finding-1")
    second = build_remediation_plan(record, "finding-1")

    assert first == second
    assert first.expected_files == ("src/service.py",)
    assert first.risk_level == "medium"
    assert first.expected_score_impact is None
    assert "do not commit, push, or merge" in first.instruction.lower()
    assert record.repository_path not in first.instruction


def test_plan_endpoint_returns_grounded_approval_gate(client: TestClient) -> None:
    record = _record()
    set_scan_provider(lambda scan_id: record if scan_id == record.scan_id else None)

    response = client.get("/api/ask-sonar/remediation-plan/scan-1/finding-1")

    assert response.status_code == 200
    data = response.json()
    assert data["plan"]["finding_id"] == "finding-1"
    assert data["plan"]["expected_files"] == ["src/service.py"]
    assert data["plan"]["expected_score_impact"] is None
    assert data["approval"] == {
        "required": True,
        "approved": False,
        "execution_performed": False,
    }
    assert data["deterministic_score_unchanged"] is True


def test_unapproved_request_never_reaches_orchestration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record()
    plan = build_remediation_plan(record, "finding-1")
    set_scan_provider(lambda scan_id: record if scan_id == record.scan_id else None)
    orchestrator = CapturingOrchestrator()
    monkeypatch.setattr(
        "app.ask_sonar.api.get_remediation_orchestrator", lambda: orchestrator
    )
    monkeypatch.setattr(
        "app.ask_sonar.api.get_authorization_service",
        lambda: CapturingAuthorizationService(),
    )

    response = client.post(
        "/api/ask-sonar/remediation/approve-and-run",
        json={
            "request_id": "request-1",
            "scan_id": "scan-1",
            "finding_id": "finding-1",
            "plan_id": plan.plan_id,
            "approved": False,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ask_sonar_remediation_approval_required"
    assert orchestrator.requests == []


def test_tampered_plan_id_is_rejected_before_orchestration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record()
    set_scan_provider(lambda scan_id: record if scan_id == record.scan_id else None)
    orchestrator = CapturingOrchestrator()
    monkeypatch.setattr(
        "app.ask_sonar.api.get_remediation_orchestrator", lambda: orchestrator
    )
    monkeypatch.setattr(
        "app.ask_sonar.api.get_authorization_service",
        lambda: CapturingAuthorizationService(),
    )

    response = client.post(
        "/api/ask-sonar/remediation/approve-and-run",
        json={
            "request_id": "request-1",
            "scan_id": "scan-1",
            "finding_id": "finding-1",
            "plan_id": "plan-tampered",
            "approved": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ask_sonar_remediation_plan_mismatch"
    assert orchestrator.requests == []


def test_approved_plan_uses_server_derived_repository_and_instruction(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    record = _record(repository_path=str(tmp_path))
    plan = build_remediation_plan(record, "finding-1")
    set_scan_provider(lambda scan_id: record if scan_id == record.scan_id else None)
    orchestrator = CapturingOrchestrator()
    monkeypatch.setattr(
        "app.ask_sonar.api.get_remediation_orchestrator", lambda: orchestrator
    )
    monkeypatch.setattr(
        "app.ask_sonar.api.get_authorization_service",
        lambda: CapturingAuthorizationService(),
    )

    response = client.post(
        "/api/ask-sonar/remediation/approve-and-run",
        json={
            "request_id": "request-1",
            "scan_id": "scan-1",
            "finding_id": "finding-1",
            "plan_id": plan.plan_id,
            "approved": True,
        },
    )

    assert response.status_code == 200
    assert len(orchestrator.requests) == 1
    request = orchestrator.requests[0]
    assert request.repository_path == str(tmp_path.resolve())
    assert request.instruction == plan.instruction
    assert request.finding_id == plan.finding_id
    assert request.scan_id == plan.scan_id
    assert request.remediation_kind == "ask_sonar_approved_patch"
    assert response.json()["workflow"]["completed"] is True


def test_legacy_record_without_slug_keeps_unavailable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Records persisted before slug tracking keep the original 409 behavior."""
    record = _record(repository_path="/tmp/definitely-not-a-real-checkout")
    assert record.repository_slug is None
    plan = build_remediation_plan(record, "finding-1")
    set_scan_provider(lambda scan_id: record if scan_id == record.scan_id else None)
    orchestrator = CapturingOrchestrator()
    monkeypatch.setattr(
        "app.ask_sonar.api.get_remediation_orchestrator", lambda: orchestrator
    )
    monkeypatch.setattr(
        "app.ask_sonar.api.get_authorization_service",
        lambda: CapturingAuthorizationService(),
    )

    response = client.post(
        "/api/ask-sonar/remediation/approve-and-run",
        json={
            "request_id": "request-1",
            "scan_id": "scan-1",
            "finding_id": "finding-1",
            "plan_id": plan.plan_id,
            "approved": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ask_sonar_remediation_unavailable"
    assert (
        response.json()["detail"]["message"]
        == "Remediation source repository is unavailable"
    )
    assert orchestrator.requests == []
