from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np


@dataclass(frozen=True)
class RuleSweepResult:
    side: str
    operator: str
    threshold: float
    support_n: int
    support_pct: float
    wins: int
    precision: float
    base_rate: float


@dataclass(frozen=True)
class WilsonCI:
    low: float
    high: float


def wilson_ci(successes: int, n: int, z: float = 1.96) -> WilsonCI:
    if n <= 0:
        return WilsonCI(low=0.0, high=0.0)
    p = successes / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2 * n)) / denom
    margin = z * sqrt((p * (1 - p) / n) + ((z * z) / (4 * n * n))) / denom
    return WilsonCI(max(0.0, center - margin), min(1.0, center + margin))


def _best_rule_for_side(
    side: str,
    x: np.ndarray,
    y_is_up: np.ndarray,
    min_count: int,
) -> RuleSweepResult | None:
    n = x.size
    if n == 0:
        return None

    y_side = y_is_up if side == "up" else ~y_is_up
    base_rate = float(np.mean(y_side))

    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ys = y_side[order].astype(np.int64)

    uniq, first_idx, counts = np.unique(xs, return_index=True, return_counts=True)
    last_idx = first_idx + counts - 1

    prefix = np.cumsum(ys)
    total = int(prefix[-1]) if n else 0

    best: RuleSweepResult | None = None

    # <= threshold
    n_le = last_idx + 1
    wins_le = prefix[last_idx]
    for i, t in enumerate(uniq):
        cnt = int(n_le[i])
        if cnt < min_count:
            continue
        wins = int(wins_le[i])
        prec = wins / cnt if cnt else 0.0
        cand = RuleSweepResult(
            side=side,
            operator="<=",
            threshold=float(t),
            support_n=cnt,
            support_pct=cnt / n,
            wins=wins,
            precision=prec,
            base_rate=base_rate,
        )
        if (best is None) or (cand.precision > best.precision) or (
            np.isclose(cand.precision, best.precision) and cand.support_n > best.support_n
        ):
            best = cand

    # >= threshold
    wins_before_first = np.where(first_idx > 0, prefix[first_idx - 1], 0)
    n_ge = n - first_idx
    wins_ge = total - wins_before_first
    for i, t in enumerate(uniq):
        cnt = int(n_ge[i])
        if cnt < min_count:
            continue
        wins = int(wins_ge[i])
        prec = wins / cnt if cnt else 0.0
        cand = RuleSweepResult(
            side=side,
            operator=">=",
            threshold=float(t),
            support_n=cnt,
            support_pct=cnt / n,
            wins=wins,
            precision=prec,
            base_rate=base_rate,
        )
        if (best is None) or (cand.precision > best.precision) or (
            np.isclose(cand.precision, best.precision) and cand.support_n > best.support_n
        ):
            best = cand

    return best


def best_rules_for_both_sides(
    values: np.ndarray,
    outcomes: np.ndarray,
    min_support_n: int,
    min_support_pct: float,
) -> dict[str, RuleSweepResult | None]:
    n = values.size
    if n == 0:
        return {"up": None, "down": None}
    min_count = max(min_support_n, int(np.ceil(n * min_support_pct)))
    return {
        "up": _best_rule_for_side("up", values, outcomes, min_count),
        "down": _best_rule_for_side("down", values, outcomes, min_count),
    }


def evaluate_threshold_rule(
    values: np.ndarray,
    outcomes: np.ndarray,
    prediction: str,
    operator: str,
    threshold: float,
) -> dict[str, float | int]:
    if operator == ">=":
        mask = values >= threshold
    elif operator == "<=":
        mask = values <= threshold
    else:
        raise ValueError(f"Unsupported operator: {operator}")

    support_n = int(mask.sum())
    if support_n == 0:
        return {
            "support_n": 0,
            "wins": 0,
            "accuracy": 0.0,
            "support_pct": 0.0,
            "base_rate": 0.0,
            "lift": 0.0,
        }

    pred_is_up = prediction == "up"
    y = outcomes[mask]
    wins = int(np.sum(y if pred_is_up else ~y))
    acc = wins / support_n

    base_rate = float(np.mean(outcomes if pred_is_up else ~outcomes))
    return {
        "support_n": support_n,
        "wins": wins,
        "accuracy": acc,
        "support_pct": support_n / values.size,
        "base_rate": base_rate,
        "lift": acc - base_rate,
    }
