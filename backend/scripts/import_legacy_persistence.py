"""Explicit, idempotent import of legacy Code Sonar JSON/JSONL files."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select

from app.history import ScanRecord
from app.persistence.repositories import _tenant
from app.persistence.runtime import configure_persistence_from_env
from app.persistence.schema import (
    github_installations,
    migration_ledger,
    remediation_outcomes,
    webhook_deliveries,
    webhook_jobs,
)
from app.projects import ProjectRecord
from app.security.tenant import bind_tenant, reset_tenant


def _rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("Legacy JSON source must contain a list")
    return [dict(item) for item in payload]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, help="Operator-selected destination tenant")
    parser.add_argument(
        "--kind",
        required=True,
        choices=(
            "history",
            "projects",
            "github-installations",
            "webhook-deliveries",
            "webhook-jobs",
            "remediation-outcomes",
        ),
    )
    parser.add_argument("--source", required=True, type=Path)
    return parser.parse_args()


def _load_rows(source_path: Path) -> tuple[Path, str, list[dict[str, Any]]]:
    source = source_path.resolve(strict=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return source, digest, _rows(source)


def _already_imported(connection: Any, tenant: str, digest: str, row_count: int) -> bool:
    prior = connection.execute(
        select(migration_ledger.c.record_count).where(
            migration_ledger.c.tenant_id == tenant,
            migration_ledger.c.source_sha256 == digest,
        )
    ).scalar_one_or_none()
    if prior is None:
        return False
    if prior != row_count:
        raise RuntimeError("Legacy import ledger count mismatch")
    print(json.dumps({"status": "already_imported", "count": prior, "sha256": digest}))
    return True


def _import_history_rows(connection: Any, persistence: Any, tenant: str, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row["tenant_id"] = tenant
        persistence.history._append(connection, ScanRecord.from_dict(row))


def _import_project_rows(connection: Any, persistence: Any, tenant: str, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row["tenant_id"] = tenant
        persistence.projects._upsert(connection, ProjectRecord(**row))


def _import_github_installations(connection: Any, tenant: str, rows: list[dict[str, Any]]) -> None:
    connection.execute(
        insert(github_installations),
        [
            {
                **row,
                "tenant_id": tenant,
                "installation_id": str(row["installation_id"]),
            }
            for row in rows
        ],
    )


def _import_webhook_deliveries(connection: Any, tenant: str, rows: list[dict[str, Any]]) -> None:
    connection.execute(
        insert(webhook_deliveries),
        [
            {
                "tenant_id": tenant,
                "delivery_id": row["delivery_id"],
                "payload": {**row, "tenant_id": tenant},
            }
            for row in rows
        ],
    )


def _import_webhook_jobs(connection: Any, tenant: str, rows: list[dict[str, Any]]) -> None:
    connection.execute(
        insert(webhook_jobs),
        [
            {
                "tenant_id": tenant,
                "job_id": row["job_id"],
                "delivery_id": row["delivery_id"],
                "project_id": row["project_id"],
                "payload": {**row, "tenant_id": tenant},
                "state": row["state"],
            }
            for row in rows
        ],
    )


def _import_remediation_outcomes(connection: Any, tenant: str, rows: list[dict[str, Any]]) -> None:
    connection.execute(
        insert(remediation_outcomes),
        [
            {
                "tenant_id": tenant,
                "outcome_id": row["outcome_id"],
                "repository_id": row["repository_id"],
                "before_scan_id": row["before_scan_id"],
                "after_scan_id": row["after_scan_id"],
                "payload": row,
            }
            for row in rows
        ],
    )


def _import_kind(connection: Any, persistence: Any, tenant: str, kind: str, rows: list[dict[str, Any]]) -> None:
    if kind == "history":
        _import_history_rows(connection, persistence, tenant, rows)
    elif kind == "projects":
        _import_project_rows(connection, persistence, tenant, rows)
    elif kind == "github-installations":
        _import_github_installations(connection, tenant, rows)
    elif kind == "webhook-deliveries":
        _import_webhook_deliveries(connection, tenant, rows)
    elif kind == "webhook-jobs":
        _import_webhook_jobs(connection, tenant, rows)
    else:
        _import_remediation_outcomes(connection, tenant, rows)


def _record_ledger_entry(connection: Any, tenant: str, source: Path, digest: str, row_count: int) -> None:
    connection.execute(
        insert(migration_ledger).values(
            import_id=uuid.uuid4().hex,
            tenant_id=tenant,
            source_path=str(source),
            source_sha256=digest,
            record_count=row_count,
            imported_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _import_rows(
    connection: Any,
    persistence: Any,
    tenant: str,
    kind: str,
    source: Path,
    digest: str,
    rows: list[dict[str, Any]],
) -> None:
    if _already_imported(connection, tenant, digest, len(rows)):
        return
    _tenant(connection, tenant)
    _import_kind(connection, persistence, tenant, kind, rows)
    _record_ledger_entry(connection, tenant, source, digest, len(rows))


def main() -> int:
    args = _parse_args()
    source, digest, rows = _load_rows(args.source)
    persistence = configure_persistence_from_env()
    if persistence is None:
        raise RuntimeError("Legacy import requires configured SQL persistence")
    tenant_token = bind_tenant(args.tenant)
    try:
        with persistence.engine.begin() as connection:
            _import_rows(connection, persistence, args.tenant, args.kind, source, digest, rows)
    finally:
        reset_tenant(tenant_token)
    print(json.dumps({"status": "imported", "count": len(rows), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
