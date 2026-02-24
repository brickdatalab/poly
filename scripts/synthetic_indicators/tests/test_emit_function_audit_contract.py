from pathlib import Path


def test_emit_function_writes_runtime_audit_even_with_no_signals():
    sql = Path(
        "supabase/migrations/20260211_210000_create_codex_signal_runtime_audit.sql"
    ).read_text().lower()
    required = [
        "create or replace function indicators.fn_emit_codex_signals_for_bucket",
        "insert into indicators.codex_signal_runtime_audit",
        "on conflict (pair, bucket_time)",
        "evaluation_status",
        "rules_with_inputs",
        "rules_passed",
        "missing_inputs",
    ]
    for token in required:
        assert token in sql
