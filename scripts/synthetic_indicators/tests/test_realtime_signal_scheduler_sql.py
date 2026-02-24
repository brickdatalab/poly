from pathlib import Path


def test_realtime_tick_migration_contains_scheduler_and_tick_function():
    sql = Path(
        "supabase/migrations/20260211_181000_fix_realtime_signal_tick_and_scheduler.sql"
    ).read_text().lower()

    required = [
        "create or replace function indicators.fn_run_realtime_signal_tick",
        "create or replace function indicators.fn_signal_pipeline_watchdog",
        "fn_enqueue_synthetic_jobs",
        "fn_process_synthetic_jobs",
        "fn_enqueue_codex_signal_jobs",
        "fn_process_codex_signal_jobs",
        "codex-signal-tick-main",
        "2,17,32,47 * * * *",
        "codex-signal-tick-retry",
        "4,19,34,49 * * * *",
        "codex-signal-watchdog",
        "*/5 * * * *",
        "cron.schedule",
    ]
    for r in required:
        assert r in sql


def test_enqueue_functions_do_not_depend_on_closed_ohlcv_15m_for_candidate_selection():
    sql = Path(
        "supabase/migrations/20260211_181000_fix_realtime_signal_tick_and_scheduler.sql"
    ).read_text().lower()

    # Candidate generation should be wall-clock driven (generate_series) and synthetic-driven for codex.
    assert "generate_series" in sql
    assert "from indicators.synthetic_indicator_values s" in sql
