from pathlib import Path


def test_compute_functions_defined_and_commented():
    sql = Path("supabase/migrations/20260211_152000_create_synthetic_compute_functions.sql").read_text().lower()
    required = [
        "create or replace function indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio",
        "create or replace function indicators.fn_compute_synthetic_rsi_velocity_5m",
        "create or replace function indicators.fn_compute_synthetic_early_impulse_liq_align_2m",
        "create or replace function indicators.fn_compute_synthetic_oi_funding_impulse_2m",
        "create or replace function indicators.fn_compute_synthetic_early_momentum_divergence",
        "create or replace function indicators.fn_compute_synthetic_order_flow_accel_regime",
        "comment on function indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio",
    ]
    for r in required:
        assert r in sql
