from pathlib import Path


def test_seed_sql_includes_all_six_config_ids():
    sql = Path("supabase/migrations/20260211_151000_seed_synthetic_indicator_configs.sql").read_text()
    expected = [
        "syn_mtf_signed_efficiency_ratio_5m12_15m8",
        "syn_rsi_velocity_5m_3bar_z20",
        "syn_early_impulse_liq_align_tplus2",
        "syn_oi_funding_impulse_tplus2",
        "syn_early_momentum_divergence_tplus1",
        "syn_order_flow_accel_regime_tplus2",
    ]
    for e in expected:
        assert e in sql
