from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.codex_signals_playground.dashboard_core import (
    bucket_for_decision,
    next_decision_after,
    summarize_pair_window,
)


def dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_next_decision_after_rolls_minute_slots():
    assert next_decision_after(dt("2026-02-11T16:01:10Z")) == dt("2026-02-11T16:02:00Z")
    assert next_decision_after(dt("2026-02-11T16:02:00Z")) == dt("2026-02-11T16:17:00Z")
    assert next_decision_after(dt("2026-02-11T16:47:00Z")) == dt("2026-02-11T17:02:00Z")


def test_bucket_for_decision_is_two_minutes_back():
    assert bucket_for_decision(dt("2026-02-11T16:02:00Z")) == dt("2026-02-11T16:00:00Z")
    assert bucket_for_decision(dt("2026-02-11T16:17:00Z")) == dt("2026-02-11T16:15:00Z")
    assert bucket_for_decision(dt("2026-02-11T17:02:00Z")) == dt("2026-02-11T17:00:00Z")


def test_summarize_pair_window_no_rows_is_no_pass():
    out = summarize_pair_window(pair="BTC-USD", bucket_time=dt("2026-02-11T16:00:00Z"), rows=[], sigma_std_by_config={})
    assert out["signal_fired"] is False
    assert out["filter_pass"] is False
    assert out["prediction"] == "none"


def test_summarize_pair_window_pick_weighted_side_and_sigma_filter():
    rows = [
        {
            "rule_id": "r1",
            "prediction": "down",
            "base_accuracy": 0.61,
            "indicator_value": 12.0,
            "config_id": "cfg_a",
            "threshold": 10.0,
            "operator": ">=",
            "signals_passed": 1,
        },
        {
            "rule_id": "r2",
            "prediction": "up",
            "base_accuracy": 0.65,
            "indicator_value": 8.2,
            "config_id": "cfg_b",
            "threshold": 8.0,
            "operator": ">=",
            "signals_passed": 1,
        },
        {
            "rule_id": "r3",
            "prediction": "up",
            "base_accuracy": 0.67,
            "indicator_value": 8.8,
            "config_id": "cfg_b",
            "threshold": 8.0,
            "operator": ">=",
            "signals_passed": 2,
        },
    ]
    out = summarize_pair_window(
        pair="ETH-USD",
        bucket_time=dt("2026-02-11T16:15:00Z"),
        rows=rows,
        sigma_std_by_config={"cfg_b": 0.4, "cfg_a": 1.0},
        sigma_min=0.25,
    )
    assert out["signal_fired"] is True
    assert out["prediction"] == "up"
    assert out["filter_pass"] is True
    assert out["sigma_from_threshold"] == 2.0
    assert out["rules_passed"] == 3
