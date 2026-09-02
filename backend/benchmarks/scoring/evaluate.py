"""Dependency-free scoring benchmark metrics for blinded expert labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

GRADE = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}


def _ranks(values: list[int]) -> list[float]:
    result = [0.0] * len(values)
    for value in set(values):
        positions = [index for index, item in enumerate(values) if item == value]
        average = sum(position + 1 for position in positions) / len(positions)
        for position in positions:
            result[position] = average
    return result


def _correlation(left: list[int], right: list[int]) -> float | None:
    if len(left) < 2:
        return None
    x, y = _ranks(left), _ranks(right)
    x_mean, y_mean = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True))
    denominator = (
        sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y)
    ) ** 0.5
    return numerator / denominator if denominator else None


def evaluate(cases: list[dict[str, str]]) -> dict[str, float | int | None]:
    usable = [case for case in cases if case.get("actual_grade") and case.get("expert_grade")]
    actual = [GRADE[case["actual_grade"]] for case in usable]
    expert = [GRADE[case["expert_grade"]] for case in usable]
    count = len(usable)
    return {
        "case_count": count,
        "exact_grade_agreement": (
            sum(a == e for a, e in zip(actual, expert, strict=True)) / count
            if count
            else None
        ),
        "within_one_band_agreement": (
            sum(abs(a - e) <= 1 for a, e in zip(actual, expert, strict=True)) / count
            if count
            else None
        ),
        "spearman_rank_correlation": _correlation(actual, expert),
    }


if __name__ == "__main__":
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(evaluate(manifest["cases"]), indent=2, sort_keys=True))
