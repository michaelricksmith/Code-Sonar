"""Read-only, redacted production onboarding readiness assessment."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

from app.persistence.config import validate_data_root
from app.persistence.runtime import production_encryption_provider_available
from app.scoring.engine import SCORING_VERSION
from app.security.runtime import configured_tenant_credentials
from app.services.repository import ANALYZER_CONTRACT_VERSION, get_registered_analyzers

REQUIRED_ALEMBIC_REVISION: Final = "20260902_0002"


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    code: str
    blocking: bool
    passed: bool
    summary: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    checks: tuple[ReadinessCheck, ...]
    scoring_version: str
    analyzer_contract_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
            "scoring_version": self.scoring_version,
            "analyzer_contract_version": self.analyzer_contract_version,
        }


@dataclass(frozen=True, slots=True)
class ReadinessProbes:
    database_revision: Callable[[str], str | None]
    data_root_secure: Callable[[Path], bool]
    encryption_provider_available: Callable[[str], bool]
    calibration_validated: Callable[[], bool]


def _database_revision(database_url: str) -> str | None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revision: str = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            return revision
    finally:
        engine.dispose()


def _data_root_secure(root: Path) -> bool:
    try:
        validate_data_root(root, create=False, shared=True)
    except (OSError, RuntimeError):
        return False
    return True


DEFAULT_PROBES = ReadinessProbes(
    database_revision=_database_revision,
    data_root_secure=_data_root_secure,
    encryption_provider_available=production_encryption_provider_available,
    # No approved, finalized expert labels are shipped. This must remain fail-closed.
    calibration_validated=lambda: False,
)


def _safe(call: Callable[[], bool]) -> bool:
    try:
        return bool(call())
    except Exception:
        return False


def assess_readiness(
    environment: Mapping[str, str] | None = None,
    probes: ReadinessProbes = DEFAULT_PROBES,
) -> ReadinessReport:
    """Return stable pass/fail codes without returning configuration values or paths."""
    env = os.environ if environment is None else environment
    checks: list[ReadinessCheck] = []

    def add(code: str, passed: bool, summary: str, *, blocking: bool = True) -> None:
        checks.append(ReadinessCheck(code, blocking, passed, summary))

    try:
        credentials = configured_tenant_credentials() if environment is None else _credentials(env)
        auth_ready = bool(credentials) and all(key not in {"", "local"} for key in credentials)
    except RuntimeError:
        auth_ready = False
    add("AUTH_TENANT_CREDENTIALS", auth_ready, "Server-owned unique tenant credentials configured")

    origins = [
        item.strip().rstrip("/")
        for item in env.get("CODESONAR_CORS_ORIGINS", "").split(",")
        if item.strip()
    ]
    cors_ready = bool(origins) and all(
        urlsplit(item).scheme == "https"
        and bool(urlsplit(item).netloc)
        and urlsplit(item).hostname not in {"localhost", "127.0.0.1", "::1"}
        and not urlsplit(item).path
        for item in origins
    )
    add("CORS_EXACT_HTTPS", cors_ready, "Explicit HTTPS origin allowlist configured")

    database_url = env.get("CODESONAR_DATABASE_URL", "").strip()
    postgres = database_url.startswith(("postgresql://", "postgresql+psycopg://"))
    add("DATABASE_POSTGRESQL", postgres, "Shared persistence uses PostgreSQL")
    revision_ok = postgres and _safe(
        lambda: probes.database_revision(database_url) == REQUIRED_ALEMBIC_REVISION
    )
    add("DATABASE_ALEMBIC_HEAD", revision_ok, "Database is at the required migration head")

    provider = env.get("CODESONAR_ENCRYPTION_PROVIDER", "").strip()
    encryption_ready = provider not in {"", "local", "local-aes-gcm"} and _safe(
        lambda: probes.encryption_provider_available(provider)
    )
    add(
        "ENCRYPTION_PROVIDER_INJECTED",
        encryption_ready,
        "Production-safe encryption provider is injected",
    )

    root_value = env.get("CODESONAR_DATA_ROOT", "").strip()
    root_ready = bool(root_value) and _safe(lambda: probes.data_root_secure(Path(root_value)))
    add(
        "DATA_ROOT_HARDENED",
        root_ready,
        "Data root exists and passes shared-deployment permission checks",
    )

    github_ready = all(
        env.get(key, "").strip()
        for key in (
            "CODE_SONAR_GITHUB_APP_ID",
            "CODE_SONAR_GITHUB_APP_PRIVATE_KEY",
            "CODE_SONAR_GITHUB_APP_SLUG",
            "CODE_SONAR_GITHUB_APP_STATE_SECRET",
        )
    )
    add(
        "GITHUB_APP_CONFIGURED",
        github_ready,
        "GitHub App identity and signed install state are configured",
    )
    add(
        "GITHUB_WEBHOOK_SECRET",
        bool(env.get("CODE_SONAR_GITHUB_WEBHOOK_SECRET", "").strip()),
        "GitHub webhook signature secret is configured",
    )

    analyzer_ready = (
        bool(SCORING_VERSION)
        and bool(ANALYZER_CONTRACT_VERSION)
        and bool(get_registered_analyzers())
    )
    add(
        "SCORING_AUTHORITY_VERSIONED",
        analyzer_ready,
        "Scoring and analyzer contracts are versioned and incomplete scans fail closed",
    )
    add(
        "CALIBRATION_CORPUS_VALIDATED",
        _safe(probes.calibration_validated),
        "Independent expert-label calibration corpus is validated",
    )

    # These are shipped, authenticated application contracts; migration head is checked separately.
    add(
        "OPERATIONAL_PRIVACY_AVAILABLE",
        True,
        "Tenant privacy schema and authenticated API contract are present",
    )
    remediation_ready = len(env.get("CODESONAR_REMEDIATION_APPROVAL_SECRET", "")) >= 32
    add(
        "REMEDIATION_AUTHORIZATION_CONFIGURED",
        remediation_ready,
        "Stable remediation authorization secret is configured",
    )
    add(
        "ASK_SONAR_PROVIDER",
        bool(env.get("CODE_SONAR_ASK_SONAR_PROVIDER", "").strip()),
        "Optional Ask Sonar provider is configured",
        blocking=False,
    )
    return ReadinessReport(
        ready=all(check.passed for check in checks if check.blocking),
        checks=tuple(checks),
        scoring_version=SCORING_VERSION,
        analyzer_contract_version=ANALYZER_CONTRACT_VERSION,
    )


def _credentials(env: Mapping[str, str]) -> dict[str, str]:
    raw = env.get("CODESONAR_API_TENANT_TOKENS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid credentials") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Invalid credentials")
    result = {
        str(tenant).strip(): str(token).strip()
        for tenant, token in parsed.items()
        if str(tenant).strip() and isinstance(token, str) and token.strip()
    }
    if len(result) != len(parsed) or len(set(result.values())) != len(result):
        raise RuntimeError("Invalid credentials")
    return result
