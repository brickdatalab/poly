from pathlib import Path


def test_candidate_migration_contains_new_configs_and_dispatch_cases():
    sql = Path("supabase/migrations/20260211_175000_add_syn_cvd_mtc_candidates.sql").read_text().lower()
    required = [
        "syn_cvd_price_divergence_velocity_15m5_tplus2",
        "syn_multitimeframe_trend_confluence_tplus2",
        "fn_compute_synthetic_cvd_price_divergence_velocity",
        "fn_compute_synthetic_multitimeframe_trend_confluence",
        "when 'syn_cvd_price_divergence_velocity_15m5_tplus2' then",
        "when 'syn_multitimeframe_trend_confluence_tplus2' then",
    ]
    for r in required:
        assert r in sql


def test_seed_rules_migration_contains_all_pair_rules():
    sql = Path("supabase/migrations/20260211_176000_seed_codex_rules_for_syn_cvd_mtc.sql").read_text()
    required = [
        "btc_syn_cvd_div_15m5_up_le_n2p6735821664",
        "eth_syn_cvd_div_15m5_down_ge_1p7811307823",
        "sol_syn_cvd_div_15m5_up_le_n1p8259998716",
        "btc_syn_mtc_up_ge_3p0",
        "eth_syn_mtc_down_le_1p0",
        "sol_syn_mtc_up_ge_3p0",
    ]
    for r in required:
        assert r in sql


def test_updated_serving_view_includes_new_candidate_columns():
    sql = Path(
        "supabase/migrations/20260211_177000_update_v_synthetic_signal_inputs_with_new_candidates.sql"
    ).read_text()
    for col in [
        "syn_cvd_price_divergence_velocity",
        "syn_multitimeframe_trend_confluence",
        "syn_window_edge_57to01_eth_nonrolling",
    ]:
        assert col in sql
