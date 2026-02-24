from pathlib import Path


def test_codex_signal_functions_exist_and_compute_signals_passed():
    sql = Path("supabase/migrations/20260211_172000_create_codex_signal_functions.sql").read_text().lower()
    required = [
        "create or replace function indicators.fn_emit_codex_signals_for_bucket",
        "create or replace function indicators.fn_enqueue_codex_signal_jobs",
        "create or replace function indicators.fn_process_codex_signal_jobs",
        "signals_passed",
        "count(*) over",
        "bucket_time + interval '2 minutes' as decision_minute",
    ]
    for r in required:
        assert r in sql
