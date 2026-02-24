from pathlib import Path


def test_codex_enqueue_grid_fix_uses_current_quarter_hour_boundary():
    sql = Path(
        "supabase/migrations/20260211_212000_fix_codex_enqueue_grid_end.sql"
    ).read_text().lower()
    required = [
        "v_grid_end",
        "floor(extract(minute from v_now)",
        "interval '15 minutes'",
        "gs.bucket_time + interval '2 minutes' <= v_now",
        "insert into indicators.codex_signal_job_queue",
    ]
    for token in required:
        assert token in sql
