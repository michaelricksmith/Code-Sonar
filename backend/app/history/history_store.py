"""History store — pluggable persistence for ScanRecords.

The default production implementation writes one ``ScanRecord`` per
line as JSON to a file in the user's data directory (``~/.code-sonar/history.jsonl``
by default). Tests use an in-memory implementation.

Why JSONL? The MVP's data volume is tiny (a few scans per day, each
~100kB) and JSONL gives us:

- append-only writes (no rewriting on every scan)
- per-record schema flexibility (a corrupted line does not block
  reads of the others)
- easy human inspection (``cat history.jsonl | jq``)

If scan volume grows, the ``HistoryStore`` ABC is the seam: swap
the implementation for SQLite without changing call sites.

Schema versioning
-----------------

``JsonlHistoryStore.load_all`` filters out records with an unknown
``schema_version``. This guards against silent corruption when a
future release changes the snapshot shape.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Iterator

from app.history.scan_record import SCHEMA_VERSION, ScanRecord
from app.security.tenant import current_tenant_id


class HistoryStore(ABC):
    """Abstract base class for scan-history persistence."""

    @abstractmethod
    def append(self, record: ScanRecord) -> None:
        """Persist ``record``. Must be deterministic for fixed input."""

    @abstractmethod
    def load_all(
        self, repository_id: str | None = None
    ) -> list[ScanRecord]:
        """Return every persisted record, optionally filtered by repo.

        Ordering is deterministic: ascending by ``scanned_at`` then by
        ``scan_id`` (tie-breaker).
        """

    @abstractmethod
    def latest(self, repository_id: str) -> ScanRecord | None:
        """Return the most-recent record for ``repository_id`` or None."""

    @abstractmethod
    def get(self, scan_id: str) -> ScanRecord | None:
        """Return the record with ``scan_id`` or None."""


class InMemoryHistoryStore(HistoryStore):
    """In-process history store for tests."""

    def __init__(self) -> None:
        self._records: list[ScanRecord] = []

    def append(self, record: ScanRecord) -> None:
        self._records.append(record)

    def load_all(
        self, repository_id: str | None = None
    ) -> list[ScanRecord]:
        records = [
            r
            for r in self._records
            if _is_compatible_schema(r.schema_version) and r.tenant_id == current_tenant_id()
        ]
        if repository_id is not None:
            records = [r for r in records if r.repository_id == repository_id]
        return _sort_records(records)

    def latest(self, repository_id: str) -> ScanRecord | None:
        records = self.load_all(repository_id)
        return records[-1] if records else None

    def get(self, scan_id: str) -> ScanRecord | None:
        for r in self._records:
            if r.scan_id == scan_id and r.tenant_id == current_tenant_id():
                return r
        return None


class JsonlHistoryStore(HistoryStore):
    """JSONL-on-disk history store.

    Writes are atomic: ``append`` writes to a sibling temp file and
    ``os.replace``-s into place so a partial write cannot corrupt
    the main file. Reads parse every line and skip records whose
    ``schema_version`` is unknown.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            path = _default_history_path()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: ScanRecord) -> None:
        line = json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False)
        # Atomic write via sibling temp file.
        dirpath = self._path.parent
        fd, tmp_name = tempfile.mkstemp(
            prefix=".history.", suffix=".jsonl.tmp", dir=str(dirpath)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._read_existing())
                f.write(line)
                f.write("\n")
            os.replace(tmp_name, self._path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _read_existing(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def load_all(
        self, repository_id: str | None = None
    ) -> list[ScanRecord]:
        records = [r for r in self._iter_records() if r.tenant_id == current_tenant_id()]
        if repository_id is not None:
            records = [r for r in records if r.repository_id == repository_id]
        return _sort_records(records)

    def latest(self, repository_id: str) -> ScanRecord | None:
        records = self.load_all(repository_id)
        return records[-1] if records else None

    def get(self, scan_id: str) -> ScanRecord | None:
        for r in self._iter_records():
            if r.scan_id == scan_id and r.tenant_id == current_tenant_id():
                return r
        return None

    def _iter_records(self) -> Iterator[ScanRecord]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # Skip corrupt lines — do not let one bad row poison
                # the whole history.
                continue
            if not _is_compatible_schema(data.get("schema_version", "")):
                # Unknown schema version. Skip and continue; the
                # dashboard will show a warning if the latest record
                # was filtered.
                continue
            try:
                yield ScanRecord.from_dict(data)
            except (KeyError, TypeError, ValueError):
                # Defensive: skip malformed records.
                continue


def _sort_records(records: Iterable[ScanRecord]) -> list[ScanRecord]:
    """Stable ordering: ascending ``scanned_at`` then ``scan_id``.

    Two records with the same ``scanned_at`` (rare but possible for
    test fixtures) are ordered deterministically by ``scan_id`` so
    repeated ``load_all`` calls return the same sequence.
    """
    return sorted(records, key=lambda r: (r.scanned_at, r.scan_id))


def _is_compatible_schema(record_version: str) -> bool:
    """Return True when ``record_version`` can be safely loaded.

    A record is compatible if and only if its ``schema_version``
    equals the running code's ``SCHEMA_VERSION``. Future versions
    are skipped silently: the running code does not know how to
    interpret a record shape it never produced, and the cost of a
    mis-read (silent corruption) is higher than the cost of a
    dropped record (one missing scan summary).
    """
    return record_version == SCHEMA_VERSION


def _default_history_path() -> Path:
    """Return the default JSONL path under the user's home dir."""
    home = Path(os.environ.get("CODESONAR_HOME", str(Path.home())))
    return home / ".code-sonar" / "history.jsonl"
