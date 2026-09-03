from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.readiness import REQUIRED_ALEMBIC_REVISION, ReadinessProbes, assess_readiness


def _environment() -> dict[str, str]:
    return {
        "CODESONAR_API_TENANT_TOKENS": json.dumps(
            {"customer-a": "tenant-a-secret-value", "customer-b": "tenant-b-secret-value"}
        ),
        "CODESONAR_CORS_ORIGINS": "https://console.example.test",
        "CODESONAR_DATABASE_URL": "postgresql+psycopg://user:password@db.internal/sonar",
        "CODESONAR_ENCRYPTION_PROVIDER": "kms-envelope-v1",
        "CODESONAR_DATA_ROOT": "/private/code-sonar",
        "CODE_SONAR_GITHUB_APP_ID": "12345",
        "CODE_SONAR_GITHUB_APP_PRIVATE_KEY": "private-key-material",
        "CODE_SONAR_GITHUB_APP_SLUG": "code-sonar",
        "CODE_SONAR_GITHUB_APP_STATE_SECRET": "state-secret-material",
        "CODE_SONAR_GITHUB_WEBHOOK_SECRET": "webhook-secret-material",
        "CODESONAR_REMEDIATION_APPROVAL_SECRET": "r" * 32,
    }


def _probes(*, calibrated: bool = True) -> ReadinessProbes:
    return ReadinessProbes(
        database_revision=lambda _url: REQUIRED_ALEMBIC_REVISION,
        data_root_secure=lambda _root: True,
        encryption_provider_available=lambda name: name == "kms-envelope-v1",
        calibration_validated=lambda: calibrated,
    )


def test_secure_complete_configuration_is_ready() -> None:
    report = assess_readiness(_environment(), _probes())

    assert report.ready is True
    assert all(check.passed for check in report.checks if check.blocking)
    assert next(c for c in report.checks if c.code == "ASK_SONAR_PROVIDER").blocking is False


def test_incomplete_configuration_fails_with_stable_codes() -> None:
    report = assess_readiness({}, _probes(calibrated=False))

    assert report.ready is False
    assert [check.code for check in report.checks] == [
        "AUTH_TENANT_CREDENTIALS",
        "CORS_EXACT_HTTPS",
        "DATABASE_POSTGRESQL",
        "DATABASE_ALEMBIC_HEAD",
        "ENCRYPTION_PROVIDER_INJECTED",
        "DATA_ROOT_HARDENED",
        "GITHUB_APP_CONFIGURED",
        "GITHUB_WEBHOOK_SECRET",
        "SCORING_AUTHORITY_VERSIONED",
        "CALIBRATION_CORPUS_VALIDATED",
        "OPERATIONAL_PRIVACY_AVAILABLE",
        "REMEDIATION_AUTHORIZATION_CONFIGURED",
        "ASK_SONAR_PROVIDER",
    ]


def test_default_calibration_probe_remains_not_validated() -> None:
    report = assess_readiness(_environment())
    check = next(c for c in report.checks if c.code == "CALIBRATION_CORPUS_VALIDATED")
    assert check.passed is False
    assert check.blocking is True
    assert report.ready is False


def test_report_never_exposes_secret_values_or_paths() -> None:
    environment = _environment()
    rendered = json.dumps(assess_readiness(environment, _probes()).to_dict())

    for value in environment.values():
        assert value not in rendered
    assert "password" not in rendered
    assert "/private/code-sonar" not in rendered


def test_probe_failures_are_redacted_and_fail_closed() -> None:
    def fail(_value: str | Path) -> bool:
        raise RuntimeError("secret database.example/private")

    probes = ReadinessProbes(
        database_revision=lambda _url: (_ for _ in ()).throw(RuntimeError("password")),
        data_root_secure=fail,
        encryption_provider_available=fail,
        calibration_validated=lambda: False,
    )
    rendered = json.dumps(assess_readiness(_environment(), probes).to_dict())

    assert "password" not in rendered
    assert "database.example" not in rendered
    assert '"ready": false' in rendered


def test_readiness_endpoint_requires_a_tenant_credential(monkeypatch) -> None:
    monkeypatch.setenv(
        "CODESONAR_API_TENANT_TOKENS",
        json.dumps({"customer-a": "token-a", "customer-b": "token-b"}),
    )
    client = TestClient(app)

    assert client.get("/api/ops/readiness").status_code == 401
    first = client.get("/api/ops/readiness", headers={"Authorization": "Bearer token-a"})
    second = client.get("/api/ops/readiness", headers={"Authorization": "Bearer token-b"})

    assert first.status_code == 503
    assert second.status_code == 503
    assert first.json() == second.json()
    assert "customer-a" not in first.text
    assert "customer-b" not in second.text
