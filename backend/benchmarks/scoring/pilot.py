"""Orchestrate blinded calibration packets without fetching repositories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.calibration.metrics import evaluate
from app.calibration.pilot import (
    load_finalized_independent_labels,
    make_adjudication_packet,
    make_review_packet,
    read_json,
    validate_pilot_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate corpus metadata only")
    validate.add_argument("manifest", type=Path)
    generate = commands.add_parser("generate", help="generate blinded reviewer packets")
    generate.add_argument("manifest", type=Path)
    generate.add_argument("reviewer_ids", nargs="+")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--per-cell", type=int, default=2)
    accuracy = commands.add_parser("evaluate", help="evaluate finalized independent labels")
    accuracy.add_argument("manifest", type=Path)
    accuracy.add_argument("labels", type=Path)
    adjudicate = commands.add_parser("adjudicate", help="create disagreement-preserving form")
    adjudicate.add_argument("labels", nargs="+", type=Path)
    adjudicate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    validate_pilot_manifest(manifest)
    if args.command == "validate":
        print(json.dumps({"metadata_valid": True, "accuracy_validated": False}, sort_keys=True))
        return
    if args.command == "evaluate":
        hydrated_cases = []
        for case in manifest["cases"]:
            hydrated = {**case, "scan": read_json(args.manifest.parent / case["scan_file"])}
            if case.get("adjudicated_label_file"):
                hydrated["adjudicated_label"] = read_json(
                    args.manifest.parent / case["adjudicated_label_file"]
                )
            hydrated_cases.append(hydrated)
        hydrated = {**manifest, "cases": hydrated_cases}
        labels = [read_json(path) for path in sorted(args.labels.glob("*.json"))]
        cases = load_finalized_independent_labels(hydrated, labels)
        print(json.dumps(evaluate(cases, []), indent=2, sort_keys=True))
        return
    if args.command == "adjudicate":
        packet = make_adjudication_packet([read_json(path) for path in args.labels])
        args.output.write_text(
            json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({"adjudication_status": "draft", "accuracy_validated": False}))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    for case in manifest["cases"]:
        scan_path = args.manifest.parent / case["scan_file"]
        scan = read_json(scan_path)
        for reviewer_id in args.reviewer_ids:
            packet = make_review_packet(
                case["metadata"], scan, reviewer_id=reviewer_id, per_cell=args.per_cell
            )
            packet["benchmark_version"] = manifest["benchmark_version"]
            target = args.output / f"{case['metadata']['case_id']}-{reviewer_id}.json"
            target.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"packets_generated": True, "accuracy_validated": False}, sort_keys=True))


if __name__ == "__main__":
    main()
