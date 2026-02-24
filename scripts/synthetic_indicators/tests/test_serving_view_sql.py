from pathlib import Path


def test_serving_view_contains_all_six_signals():
    sql = Path("supabase/migrations/20260211_154000_create_v_synthetic_signal_inputs.sql").read_text()
    for col in [
        "syn_mtf_signed_efficiency_ratio",
        "syn_rsi_velocity_5m",
        "syn_early_impulse_liq_align_2m",
        "syn_oi_funding_impulse_2m",
        "syn_early_momentum_divergence",
        "syn_order_flow_accel_regime",
    ]:
        assert col in sql
