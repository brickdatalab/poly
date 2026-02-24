from pathlib import Path


def test_codex_signal_rules_seed_contains_expected_rule_ids():
    sql = Path("supabase/migrations/20260211_171000_seed_codex_signal_rules_v1.sql").read_text()
    expected = [
        "btc_syn_rsi_velocity_5m_3bar_z20_up_ge_1p489539",
        "eth_syn_early_momentum_divergence_tplus1_down_ge_0p366086",
        "sol_syn_oi_funding_impulse_tplus2_down_ge_1p606966",
    ]
    for e in expected:
        assert e in sql
