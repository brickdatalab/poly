from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1] / "research"))

from metrics import best_rules_for_both_sides, evaluate_threshold_rule, wilson_ci


def test_wilson_ci_monotonic():
    lo1 = wilson_ci(30, 50)
    lo2 = wilson_ci(60, 100)
    assert 0 <= lo1.low <= lo1.high <= 1
    assert 0 <= lo2.low <= lo2.high <= 1
    # With same proportion and larger n, CI tightens (higher low / lower high)
    assert lo2.low >= lo1.low
    assert lo2.high <= lo1.high


def test_best_rules_finds_signal():
    x = np.array([-2, -1, -0.5, 0.0, 0.2, 0.8, 1.4, 2.0], dtype=np.float64)
    y_up = np.array([False, False, False, False, True, True, True, True], dtype=bool)
    best = best_rules_for_both_sides(x, y_up, min_support_n=2, min_support_pct=0.1)
    assert best["up"] is not None
    assert best["down"] is not None
    assert best["up"].precision >= 0.75
    assert best["down"].precision >= 0.75


def test_evaluate_threshold_rule_counts_support_and_accuracy():
    x = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    y_up = np.array([True, True, False, False], dtype=bool)

    up = evaluate_threshold_rule(x, y_up, prediction="up", operator=">=", threshold=0.2)
    assert up["support_n"] == 3
    assert abs(up["accuracy"] - (1 / 3)) < 1e-9

    dn = evaluate_threshold_rule(x, y_up, prediction="down", operator=">=", threshold=0.3)
    assert dn["support_n"] == 2
    assert abs(dn["accuracy"] - 1.0) < 1e-9
