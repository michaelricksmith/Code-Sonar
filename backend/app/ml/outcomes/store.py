"""Local JSONL persistence for remediation outcome observations."""

from __future__ import annotations

import json
from pathlib import Path

from app.ml.outcomes.schema import RemediationOutcome


class JsonlOutcomeStore:
    """Append-only local store for observed remediation outcomes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".code-sonar" / "remediation-outcomes.jsonl")

    def append(self, outcome: RemediationOutcome) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(outcome.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    def load_all(self, repository_id: str | None = None) -> list[RemediationOutcome]:
        if not self.path.exists():
            return []

        outcomes: list[RemediationOutcome] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("Outcome row must be a JSON object")
                    outcome = RemediationOutcome.from_dict(payload)
                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError(
                        f"Invalid remediation outcome at line {line_number}"
                    ) from exc
                if repository_id is None or outcome.repository_id == repository_id:
                    outcomes.append(outcome)

        return sorted(outcomes, key=lambda item: (item.attempted_at, item.outcome_id))

    def get(self, outcome_id: str) -> RemediationOutcome | None:
        return next(
            (outcome for outcome in self.load_all() if outcome.outcome_id == outcome_id),
            None,
        )
