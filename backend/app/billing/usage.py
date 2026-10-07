"""Per-user monthly usage counters (scans + Ask Sonar questions).

Backend selection mirrors the user store: when SQL persistence is
configured the counters live in the ``usage_counters`` table, otherwise
they fall back to a JSON file under ``~/.code-sonar/`` (mode 0600), the
same pattern as ``oauth-users.json``.

The accounting period is the first day of the current UTC month
(YYYY-MM-DD). Counters reset automatically: reads and writes always key
on the current period, so a stored row from a previous month is simply
ignored and a fresh row starts at zero.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from sqlalchemy import Engine, insert, select, update

from app.billing.tables import usage_counters

# Sentinel user id for signed-out callers. There is deliberately no FK
# from usage_counters to users, so this id needs no user row.
ANONYMOUS_USER_ID = "anonymous"

UsageKind = Literal["scans", "ask_sonar"]

_COLUMN_FOR_KIND: dict[UsageKind, str] = {
    "scans": "scans_used",
    "ask_sonar": "ask_sonar_used",
}


def current_period_start() -> str:
    """First day of the current UTC month, formatted YYYY-MM-DD."""
    return datetime.now(timezone.utc).date().replace(day=1).isoformat()


def _fresh_usage(user_id: str, period: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "period_start": period,
        "scans_used": 0,
        "ask_sonar_used": 0,
    }


class UsageStore:
    """Monthly usage counters with a SQL backend or a JSON-file fallback."""

    def __init__(self, engine: Engine | None = None, path: Path | None = None) -> None:
        self._engine = engine
        self._path = path or (Path.home() / ".code-sonar" / "usage-counters.json")
        self._lock = RLock()

    @staticmethod
    def _key(user_id: str | None) -> str:
        return user_id or ANONYMOUS_USER_ID

    # -- public API ----------------------------------------------------

    def get_usage(self, user_id: str | None) -> dict[str, Any]:
        """Current-period counters for a user (zeros when nothing recorded)."""
        period = current_period_start()
        key = self._key(user_id)
        if self._engine is not None:
            return self._get_sql(key, period)
        return self._get_json(key, period)

    def increment(self, user_id: str | None, kind: UsageKind) -> dict[str, Any]:
        """Add one to a counter for the current period; return updated usage."""
        if kind not in _COLUMN_FOR_KIND:
            raise ValueError(f"Unknown usage kind: {kind!r}")
        period = current_period_start()
        key = self._key(user_id)
        if self._engine is not None:
            return self._increment_sql(key, period, kind)
        return self._increment_json(key, period, kind)

    def reset_usage(self, user_id: str | None) -> dict[str, Any]:
        """Zero the current-period counters (admin grant of fresh quota)."""
        period = current_period_start()
        key = self._key(user_id)
        if self._engine is not None:
            return self._reset_sql(key, period)
        return self._reset_json(key, period)

    # -- SQL backend ---------------------------------------------------

    def _get_sql(self, user_id: str, period: str) -> dict[str, Any]:
        assert self._engine is not None
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(usage_counters).where(
                        usage_counters.c.user_id == user_id,
                        usage_counters.c.period_start == period,
                    )
                )
                .mappings()
                .first()
            )
        usage = _fresh_usage(user_id, period)
        if row is not None:
            usage["scans_used"] = int(row["scans_used"])
            usage["ask_sonar_used"] = int(row["ask_sonar_used"])
        return usage

    def _increment_sql(self, user_id: str, period: str, kind: UsageKind) -> dict[str, Any]:
        assert self._engine is not None
        column = _COLUMN_FOR_KIND[kind]
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(usage_counters).where(
                        usage_counters.c.user_id == user_id,
                        usage_counters.c.period_start == period,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                values: dict[str, Any] = {
                    "id": uuid.uuid4().hex,
                    "user_id": user_id,
                    "period_start": period,
                    "scans_used": 0,
                    "ask_sonar_used": 0,
                }
                values[column] = 1
                connection.execute(insert(usage_counters).values(**values))
                usage = _fresh_usage(user_id, period)
                usage[column] = 1
                return usage
            new_value = int(row[column]) + 1
            connection.execute(
                update(usage_counters)
                .where(usage_counters.c.id == row["id"])
                .values({column: new_value})
            )
            usage = _fresh_usage(user_id, period)
            usage["scans_used"] = new_value if kind == "scans" else int(row["scans_used"])
            usage["ask_sonar_used"] = (
                new_value if kind == "ask_sonar" else int(row["ask_sonar_used"])
            )
            return usage

    # -- JSON fallback -------------------------------------------------

    def _load_json(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def _save_json(self, records: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(records, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self._path)

    @staticmethod
    def _record_dict(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": str(record.get("user_id", "")),
            "period_start": str(record.get("period_start", "")),
            "scans_used": int(record.get("scans_used", 0)),
            "ask_sonar_used": int(record.get("ask_sonar_used", 0)),
        }

    def _get_json(self, user_id: str, period: str) -> dict[str, Any]:
        with self._lock:
            for record in self._load_json():
                if record.get("user_id") == user_id and record.get("period_start") == period:
                    return self._record_dict(record)
        return _fresh_usage(user_id, period)

    def _increment_json(self, user_id: str, period: str, kind: UsageKind) -> dict[str, Any]:
        column = _COLUMN_FOR_KIND[kind]
        with self._lock:
            records = self._load_json()
            for record in records:
                if record.get("user_id") == user_id and record.get("period_start") == period:
                    record[column] = int(record.get(column, 0)) + 1
                    self._save_json(records)
                    return self._record_dict(record)
            record = {
                "id": uuid.uuid4().hex,
                "user_id": user_id,
                "period_start": period,
                "scans_used": 0,
                "ask_sonar_used": 0,
            }
            record[column] = 1
            records.append(record)
            self._save_json(records)
            return self._record_dict(record)

    def _reset_sql(self, user_id: str, period: str) -> dict[str, Any]:
        assert self._engine is not None
        with self._engine.begin() as connection:
            connection.execute(
                usage_counters.update()
                .where(
                    usage_counters.c.user_id == user_id,
                    usage_counters.c.period_start == period,
                )
                .values(scans_used=0, ask_sonar_used=0)
            )
        return _fresh_usage(user_id, period)

    def _reset_json(self, user_id: str, period: str) -> dict[str, Any]:
        with self._lock:
            records = self._load_json()
            kept = [
                r for r in records
                if not (r.get("user_id") == user_id and r.get("period_start") == period)
            ]
            if len(kept) != len(records):
                self._save_json(kept)
        return _fresh_usage(user_id, period)


_usage_store: UsageStore | None = None


def get_usage_store() -> UsageStore:
    """Return the process-wide usage store.

    SQL-backed when the persistence engine is configured, otherwise the
    JSON-file fallback. Resolved lazily so startup can configure
    persistence before the first request.
    """
    global _usage_store
    if _usage_store is not None:
        return _usage_store
    engine: Engine | None = None
    try:
        from app.persistence.runtime import get_persistence

        persistence = get_persistence()
        engine = persistence.engine if persistence is not None else None
    except Exception:
        engine = None
    _usage_store = UsageStore(engine=engine)
    return _usage_store


def set_usage_store(store: UsageStore | None) -> None:
    """Replace the process-wide usage store. Used by tests."""
    global _usage_store
    _usage_store = store
