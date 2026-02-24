from pathlib import Path


def test_codex_signal_outcome_migration_contains_required_columns_and_functions():
    sql = Path(
        "supabase/migrations/20260211_182000_add_codex_signal_outcome_columns.sql"
    ).read_text().lower()

    required = [
        "add column if not exists opening_price",
        "add column if not exists closing_price",
        "add column if not exists actual_direction",
        "add column if not exists is_accurate",
        "create or replace function indicators.fn_refresh_codex_signal_outcomes",
        "create or replace function indicators.fn_emit_codex_signals_for_bucket",
        "create or replace function indicators.fn_run_realtime_signal_tick",
        "outcomes_refreshed",
        "select indicators.fn_refresh_codex_signal_outcomes(interval '365 days')",
    ]
    for token in required:
        assert token in sql
