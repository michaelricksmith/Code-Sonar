"""Transactional persistence, tenant, and encryption invariants."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Generator

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import create_engine

from app.history import ScanRecord
from app.persistence.config import (
    PersistenceConfig,
    validate_data_root,
    validate_persistence_config,
)
from app.persistence.crypto import LocalDevelopmentEncryptionProvider, checkout_path_aad
from app.persistence.runtime import PersistenceUnitOfWork
from app.persistence.schema import metadata
from app.projects import ProjectRecord
from app.security.tenant import bind_tenant, reset_tenant
from scripts import import_legacy_persistence


def _scan(scan_id: str, tenant_id: str = "tenant-a") -> ScanRecord:
    return ScanRecord(
        scan_id=scan_id,
        tenant_id=tenant_id,
        repository_id="repo-1",
        repository_path="repo",
        scanned_at="2026-09-02T00:00:00+00:00",
        schema_version="1.0",
        scoring_version="1.0",
        score=720,
        grade="B",
        total_debt_points=10,
        finding_count=0,
        category_scores={},
        severity_distribution={},
        findings_by_category={},
        findings_source_breakdown={},
        findings=[],
    )


def _project(path: Path) -> ProjectRecord:
    return ProjectRecord(
        project_id="project-1",
        provider="github",
        owner="acme",
        name="private",
        default_branch="main",
        connected_at="now",
        local_checkout_path=str(path),
    )


@pytest.fixture
def persistence(tmp_path: Path) -> Generator[PersistenceUnitOfWork, None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'storage.db'}")
    metadata.create_all(engine)
    yield PersistenceUnitOfWork(engine, LocalDevelopmentEncryptionProvider(b"k" * 32))
    engine.dispose()


def test_checkout_path_is_encrypted_and_tenant_bound(
    persistence: PersistenceUnitOfWork, tmp_path: Path
) -> None:
    token = bind_tenant("tenant-a")
    try:
        persistence.projects.upsert(_project(tmp_path / "private-checkout"))
        loaded = persistence.projects.get("project-1")
    finally:
        reset_tenant(token)
    assert loaded is not None
    assert loaded.local_checkout_path.endswith("private-checkout")
    database = persistence.engine.url.database
    assert database is not None
    with sqlite3.connect(database) as connection:
        ciphertext = connection.execute("select checkout_path_ciphertext from projects").fetchone()[
            0
        ]
    assert "private-checkout" not in ciphertext


def test_encryption_rejects_wrong_tenant_aad() -> None:
    provider = LocalDevelopmentEncryptionProvider(b"k" * 32)
    encrypted = provider.encrypt("secret-path", aad=checkout_path_aad("a", "p"))
    with pytest.raises(InvalidTag):
        provider.decrypt(encrypted, aad=checkout_path_aad("b", "p"))


def test_project_scan_update_is_atomic(persistence: PersistenceUnitOfWork, tmp_path: Path) -> None:
    token = bind_tenant("tenant-a")
    try:
        persistence.projects.upsert(_project(tmp_path))
        persistence.record_project_scan("project-1", _scan("scan-ok"))
        assert persistence.projects.get("project-1").latest_scan_id == "scan-ok"  # type: ignore[union-attr]
        with pytest.raises(LookupError):
            persistence.record_project_scan("missing", _scan("scan-rollback"))
        assert persistence.history.get("scan-rollback") is None
    finally:
        reset_tenant(token)


def test_sql_repositories_deny_cross_tenant(
    persistence: PersistenceUnitOfWork, tmp_path: Path
) -> None:
    first = bind_tenant("tenant-a")
    try:
        persistence.projects.upsert(_project(tmp_path))
        persistence.history.append(_scan("scan-a"))
    finally:
        reset_tenant(first)
    second = bind_tenant("tenant-b")
    try:
        assert persistence.projects.get("project-1") is None
        assert persistence.history.get("scan-a") is None
    finally:
        reset_tenant(second)


def test_shared_mode_rejects_sqlite_and_local_encryption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "0")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        validate_persistence_config(
            PersistenceConfig(f"sqlite:///{tmp_path / 'unsafe.db'}", tmp_path)
        )
    with pytest.raises(RuntimeError, match="production encryption provider"):
        validate_persistence_config(
            PersistenceConfig("postgresql+psycopg://db.example/code_sonar", tmp_path)
        )


def test_local_sqlite_rejects_multiple_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODESONAR_LOCAL_DEV", "1")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="single local worker"):
        validate_persistence_config(
            PersistenceConfig(f"sqlite:///{tmp_path / 'local.db'}", tmp_path)
        )


def test_data_root_rejects_symlink_or_reparse_point(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.persistence import config

    linked = tmp_path / "linked"
    linked.mkdir()
    monkeypatch.setattr(config, "_is_link_or_reparse", lambda _: True)
    with pytest.raises(RuntimeError, match="symlink or reparse"):
        validate_data_root(linked)


def test_legacy_import_requires_tenant_and_is_idempotent(
    persistence: PersistenceUnitOfWork,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "projects.json"
    source.write_text(json.dumps([asdict(_project(tmp_path))]), encoding="utf-8")
    monkeypatch.setattr(
        import_legacy_persistence,
        "configure_persistence_from_env",
        lambda: persistence,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["import", "--tenant", "tenant-import", "--kind", "projects", "--source", str(source)],
    )
    assert import_legacy_persistence.main() == 0
    assert import_legacy_persistence.main() == 0
    token = bind_tenant("tenant-import")
    try:
        assert len(persistence.projects.list()) == 1
    finally:
        reset_tenant(token)
