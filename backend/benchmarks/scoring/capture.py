"""Capture a sanitized frozen scan: python capture.py INPUT CASE_ID OUTPUT."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.calibration.capture import capture_frozen_scan

if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: capture.py INPUT_SCAN_JSON CASE_ID EXPECTED_SCORING_VERSION OUTPUT_JSON"
        )
    scan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    versions = {
        str(x["analyzer"]): str(x.get("version", "unversioned"))
        for x in scan.get("analyzer_execution", [])
    }
    artifact = capture_frozen_scan(
        scan,
        case_id=sys.argv[2],
        analyzer_versions=versions,
        expected_scoring_version=sys.argv[3],
    )
    Path(sys.argv[4]).write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
