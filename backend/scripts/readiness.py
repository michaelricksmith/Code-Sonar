"""Print the redacted onboarding preflight report and fail until client-ready."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.readiness import assess_readiness  # noqa: E402

if __name__ == "__main__":
    report = assess_readiness()
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    raise SystemExit(0 if report.ready else 1)
