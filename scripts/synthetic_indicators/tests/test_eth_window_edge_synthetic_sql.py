from pathlib import Path


def test_eth_window_edge_synthetic_migration_has_config_and_dispatch():
    sql = Path(
        "supabase/migrations/20260211_173000_add_eth_window_edge_nonrolling_synthetic.sql"
    ).read_text().lower()
    required = [
        "syn_window_edge_57to01_eth_nonrolling_tplus2",
        "fn_compute_synthetic_window_edge_eth_nonrolling",
        "when 'syn_window_edge_57to01_eth_nonrolling_tplus2' then",
        "((v_close01 - v_open57) / v_open57) * 100.0",
    ]
    for r in required:
        assert r in sql


def test_eth_window_edge_codex_rules_seeded_sql():
    sql = Path(
        "supabase/migrations/20260211_174000_seed_codex_rules_for_eth_window_edge_synthetic.sql"
    ).read_text()
    assert "eth_syn_window_edge_57to01_nonrolling_up_ge_0p0719108856" in sql
    assert "eth_syn_window_edge_57to01_nonrolling_down_le_n0p0639929142" in sql
