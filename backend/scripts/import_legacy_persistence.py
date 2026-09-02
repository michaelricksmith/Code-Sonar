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


def main() -> int:
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
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = _rows(source)
    persistence = configure_persistence_from_env()
    if persistence is None:
        raise RuntimeError("Legacy import requires configured SQL persistence")
    tenant_token = bind_tenant(args.tenant)
    try:
        with persistence.engine.begin() as connection:
            prior = connection.execute(
                select(migration_ledger.c.record_count).where(
                    migration_ledger.c.tenant_id == args.tenant,
                    migration_ledger.c.source_sha256 == digest,
                )
            ).scalar_one_or_none()
            if prior is not None:
                if prior != len(rows):
                    raise RuntimeError("Legacy import ledger count mismatch")
                print(json.dumps({"status": "already_imported", "count": prior, "sha256": digest}))
                return 0
            _tenant(connection, args.tenant)
            if args.kind == "history":
                for row in rows:
                    row["tenant_id"] = args.tenant
                    persistence.history._append(connection, ScanRecord.from_dict(row))
            elif args.kind == "projects":
                for row in rows:
                    row["tenant_id"] = args.tenant
                    persistence.projects._upsert(connection, ProjectRecord(**row))
            elif args.kind == "github-installations":
                connection.execute(
                    insert(github_installations),
                    [
                        {
                            **row,
                            "tenant_id": args.tenant,
                            "installation_id": str(row["installation_id"]),
                        }
                        for row in rows
                    ],
                )
            elif args.kind == "webhook-deliveries":
                connection.execute(
                    insert(webhook_deliveries),
                    [
                        {
                            "tenant_id": args.tenant,
                            "delivery_id": row["delivery_id"],
                            "payload": {**row, "tenant_id": args.tenant},
                        }
                        for row in rows
                    ],
                )
            elif args.kind == "webhook-jobs":
                connection.execute(
                    insert(webhook_jobs),
                    [
                        {
                            "tenant_id": args.tenant,
                            "job_id": row["job_id"],
                            "delivery_id": row["delivery_id"],
                            "project_id": row["project_id"],
                            "payload": {**row, "tenant_id": args.tenant},
                            "state": row["state"],
                        }
                        for row in rows
                    ],
                )
            else:
                connection.execute(
                    insert(remediation_outcomes),
                    [
                        {
                            "tenant_id": args.tenant,
                            "outcome_id": row["outcome_id"],
                            "repository_id": row["repository_id"],
                            "before_scan_id": row["before_scan_id"],
                            "after_scan_id": row["after_scan_id"],
                            "payload": row,
                        }
                        for row in rows
                    ],
                )
            connection.execute(
                insert(migration_ledger).values(
                    import_id=uuid.uuid4().hex,
                    tenant_id=args.tenant,
                    source_path=str(source),
                    source_sha256=digest,
                    record_count=len(rows),
                    imported_at=datetime.now(timezone.utc).isoformat(),
                )
            )
    finally:
        reset_tenant(tenant_token)
    print(json.dumps({"status": "imported", "count": len(rows), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
