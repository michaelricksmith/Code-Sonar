"""Evaluate finalized benchmark cases and finding reviews."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.calibration.contracts import CONTRACT_VERSION
from app.calibration.metrics import evaluate
from app.scoring.engine import SCORING_VERSION

if __name__ == "__main__":
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if manifest.get("contract_version") != CONTRACT_VERSION:
        raise SystemExit("incompatible calibration contract_version")
    if manifest.get("scoring_version") != SCORING_VERSION:
        raise SystemExit("incompatible scoring_version")
    reviews_path = manifest.get("finding_reviews_file")
    reviews = json.loads(Path(reviews_path).read_text(encoding="utf-8")) if reviews_path else []
    print(json.dumps(evaluate(manifest["cases"], reviews), indent=2, sort_keys=True))
