"""Dependency-free, deterministic calibration metrics and confidence intervals."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

GRADE = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}
SEVERITY = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def _ranks(values: Sequence[float]) -> list[float]:
    result = [0.0] * len(values)
    for value in sorted(set(values)):
        positions = [i for i, item in enumerate(values) if item == value]
        rank = sum(i + 1 for i in positions) / len(positions)
        for i in positions:
            result[i] = rank
    return result


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    x, y = _ranks(left), _ranks(right)
    xm, ym = math.fsum(x) / len(x), math.fsum(y) / len(y)
    numerator = math.fsum((a - xm) * (b - ym) for a, b in zip(x, y, strict=True))
    denominator = math.sqrt(
        math.fsum((a - xm) ** 2 for a in x) * math.fsum((b - ym) ** 2 for b in y)
    )
    return numerator / denominator if denominator else None


def weighted_kappa(left: Sequence[int], right: Sequence[int], *, levels: int) -> float | None:
    if len(left) != len(right) or not left:
        return None
    observed = [[0] * levels for _ in range(levels)]
    lc, rc = [0] * levels, [0] * levels
    for a, b in zip(left, right, strict=True):
        if not 0 <= a < levels or not 0 <= b < levels:
            raise ValueError("rating outside configured levels")
        observed[a][b] += 1
        lc[a] += 1
        rc[b] += 1
    scale = max(1, (levels - 1) ** 2)
    obs = math.fsum(
        ((i - j) ** 2 / scale) * observed[i][j] for i in range(levels) for j in range(levels)
    ) / len(left)
    exp = math.fsum(
        ((i - j) ** 2 / scale) * lc[i] * rc[j] for i in range(levels) for j in range(levels)
    ) / (len(left) ** 2)
    return 1 - obs / exp if exp else (1.0 if not obs else None)


def _percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    position = p * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return (
        ordered[low]
        if low == high
        else ordered[low] + (ordered[high] - ordered[low]) * (position - low)
    )


def bootstrap_ci(
    items: Sequence[Any],
    statistic: Callable[[list[Any]], float | None],
    *,
    iterations: int = 1000,
    seed: int = 20260902,
) -> dict[str, float] | None:
    if not items or iterations < 1:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(iterations):
        value = statistic([items[rng.randrange(len(items))] for _ in items])
        if value is not None and math.isfinite(value):
            estimates.append(value)
    return (
        {"low": _percentile(estimates, 0.025), "high": _percentile(estimates, 0.975)}
        if estimates
        else None
    )


def _case_metrics(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    usable = [c for c in cases if c.get("actual_grade") in GRADE and c.get("expert_grade") in GRADE]
    actual = [GRADE[c["actual_grade"]] for c in usable]
    expert = [GRADE[c["expert_grade"]] for c in usable]
    count = len(usable)
    ordinal = [c for c in usable if isinstance(c.get("expert_ordinal_health"), (int, float))]
    return {
        "case_count": count,
        "exact_grade_agreement": (
            math.fsum(a == e for a, e in zip(actual, expert)) / count if count else None
        ),
        "within_one_band_agreement": (
            math.fsum(abs(a - e) <= 1 for a, e in zip(actual, expert)) / count if count else None
        ),
        "weighted_kappa": weighted_kappa(actual, expert, levels=5),
        "expert_ordinal_spearman": spearman(
            [GRADE[c["actual_grade"]] for c in ordinal],
            [float(c["expert_ordinal_health"]) for c in ordinal],
        ),
    }


def evaluate(cases: Sequence[dict[str, Any]], reviews: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result = _case_metrics(cases)
    metrics = (
        "exact_grade_agreement",
        "within_one_band_agreement",
        "weighted_kappa",
        "expert_ordinal_spearman",
    )

    def metric_statistic(name: str) -> Callable[[list[Any]], float | None]:
        def calculate(sample: list[Any]) -> float | None:
            value = _case_metrics(sample).get(name)
            return float(value) if isinstance(value, (int, float)) else None

        return calculate

    result["confidence_intervals"] = {
        name: bootstrap_ci(list(cases), metric_statistic(name)) for name in metrics
    }
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    severity = []
    for review in reviews:
        if review.get("verdict") in {"true_positive", "false_positive"}:
            pair = counts[str(review["analyzer"])]
            pair[1] += 1
            pair[0] += review["verdict"] == "true_positive"
        a, b = review.get("reported_severity"), review.get("expert_severity")
        if a in SEVERITY and b in SEVERITY:
            severity.append((SEVERITY[a], SEVERITY[b]))

    def precision(sample: list[Any]) -> float | None:
        decided = [
            item for item in sample if item.get("verdict") in {"true_positive", "false_positive"}
        ]
        return (
            math.fsum(item["verdict"] == "true_positive" for item in decided) / len(decided)
            if decided
            else None
        )

    result["per_analyzer_precision"] = {}
    for analyzer, values in sorted(counts.items()):
        analyzer_reviews = [item for item in reviews if str(item.get("analyzer")) == analyzer]
        result["per_analyzer_precision"][analyzer] = {
            "true_positive": values[0],
            "reviewed": values[1],
            "precision": values[0] / values[1],
            "confidence_interval": bootstrap_ci(analyzer_reviews, precision),
        }

    def severity_exact(sample: list[Any]) -> float | None:
        return math.fsum(a == b for a, b in sample) / len(sample) if sample else None

    def severity_kappa(sample: list[Any]) -> float | None:
        return weighted_kappa([a for a, _ in sample], [b for _, b in sample], levels=4)

    result["severity_agreement"] = {
        "count": len(severity),
        "exact": math.fsum(a == b for a, b in severity) / len(severity) if severity else None,
        "weighted_kappa": weighted_kappa(
            [a for a, _ in severity], [b for _, b in severity], levels=4
        ),
        "confidence_intervals": {
            "exact": bootstrap_ci(severity, severity_exact),
            "weighted_kappa": bootstrap_ci(severity, severity_kappa),
        },
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        for key, value in sorted(case.get("strata", {}).items()):
            grouped[f"{key}={value}"].append(case)
    result["strata"] = {name: _case_metrics(group) for name, group in sorted(grouped.items())}
    return result
