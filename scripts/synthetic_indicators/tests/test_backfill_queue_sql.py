from pathlib import Path


def test_backfill_and_queue_functions_exist():
    sql = Path("supabase/migrations/20260211_153000_create_synthetic_backfill_and_queue_functions.sql").read_text().lower()
    for name in [
        "fn_backfill_synthetic_indicators",
        "fn_enqueue_synthetic_jobs",
        "fn_process_synthetic_jobs",
    ]:
        assert name in sql
