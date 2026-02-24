from pathlib import Path


def test_runtime_audit_migration_contains_expected_objects():
    sql = Path(
        "supabase/migrations/20260211_210000_create_codex_signal_runtime_audit.sql"
    ).read_text().lower()

    required = [
        "create table if not exists indicators.codex_signal_runtime_audit",
        "unique (pair, bucket_time)",
        "evaluation_status",
        "missing_inputs",
        "create or replace function indicators.fn_enqueue_codex_signal_jobs",
        "create or replace function indicators.fn_emit_codex_signals_for_bucket",
        "insert into indicators.codex_signal_runtime_audit",
        "on conflict (pair, bucket_time)",
        "'stale_inputs'",
        "'no_signal'",
        "'emitted'",
        "'error'",
    ]
    for token in required:
        assert token in sql
