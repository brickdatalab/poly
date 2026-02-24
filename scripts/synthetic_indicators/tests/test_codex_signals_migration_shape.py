from pathlib import Path


def test_codex_signals_migration_has_required_tables_and_uniques():
    sql = Path("supabase/migrations/20260211_170000_create_codex_signals_tables.sql").read_text().lower()
    required = [
        "create table if not exists indicators.codex_signal_rules",
        "create table if not exists indicators.codex_signals",
        "create table if not exists indicators.codex_signal_job_queue",
        "signals_passed integer not null default 1",
        "unique (pair, bucket_time, rule_id)",
        "comment on table indicators.codex_signals",
    ]
    for r in required:
        assert r in sql
