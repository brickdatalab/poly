from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_now_executor import apply_indicator_values_to_rules, fetch_active_rules, filter_rules_for_phase  # type: ignore
from run_bucket_phases import build_phase_run_times  # type: ignore


def test_apply_indicator_values_marks_passes_from_engine_values() -> None:
    rules = [
        {
            "pair": "ETH-USD",
            "config_id": "syn_multitimeframe_trend_confluence_tplus2",
            "operator": ">=",
            "threshold": 3.0,
            "prediction": "up",
            "base_accuracy": 0.75,
            "rule_id": "eth_rule",
        }
    ]
    values = {("ETH-USD", "syn_multitimeframe_trend_confluence_tplus2"): 3.0}
    out = apply_indicator_values_to_rules(rules, values)
    assert out[0]["value_v1"] == 3.0
    assert out[0]["passes"] is True


def test_apply_indicator_values_marks_missing_when_absent() -> None:
    rules = [
        {
            "pair": "BTC-USD",
            "config_id": "syn_early_momentum_divergence_tplus1",
            "operator": ">=",
            "threshold": 0.1,
            "prediction": "down",
            "base_accuracy": 0.64,
            "rule_id": "btc_rule",
        }
    ]
    values = {}
    out = apply_indicator_values_to_rules(rules, values)
    assert out[0]["value_v1"] is None
    assert out[0]["passes"] is False


def test_build_phase_run_times_defaults() -> None:
    bucket = datetime(2026, 2, 13, 3, 0, 0, tzinfo=timezone.utc)
    phases = build_phase_run_times(bucket)
    assert phases[0]["phase"] == "t0"
    assert phases[0]["run_at"] == datetime(2026, 2, 13, 3, 0, 0, tzinfo=timezone.utc)
    assert phases[1]["phase"] == "t_plus_1"
    assert phases[1]["run_at"] == datetime(2026, 2, 13, 3, 1, 14, tzinfo=timezone.utc)
    assert phases[2]["phase"] == "t_plus_2"
    assert phases[2]["run_at"] == datetime(2026, 2, 13, 3, 2, 0, tzinfo=timezone.utc)


def test_filter_rules_for_phase_keeps_expected_configs() -> None:
    rules = [
        {"config_id": "syn_early_momentum_divergence_tplus1"},
        {"config_id": "syn_multitimeframe_trend_confluence_tplus2"},
    ]
    p1 = filter_rules_for_phase(rules, "t_plus_1")
    p2 = filter_rules_for_phase(rules, "t_plus_2")
    assert [r["config_id"] for r in p1] == ["syn_early_momentum_divergence_tplus1"]
    assert sorted(r["config_id"] for r in p2) == [
        "syn_early_momentum_divergence_tplus1",
        "syn_multitimeframe_trend_confluence_tplus2",
    ]


def test_fetch_active_rules_is_hardcoded_for_btc_eth() -> None:
    rules = fetch_active_rules(["BTC-USD", "ETH-USD"])
    assert len(rules) == 13
    assert {r["pair"] for r in rules} == {"BTC-USD", "ETH-USD"}


def test_phase_counts_for_hardcoded_btc_eth_rules() -> None:
    rules = fetch_active_rules(["BTC-USD", "ETH-USD"])
    assert len(filter_rules_for_phase(rules, "t0")) == 0
    assert len(filter_rules_for_phase(rules, "t_plus_1")) == 9
    assert len(filter_rules_for_phase(rules, "t_plus_2")) == 13
