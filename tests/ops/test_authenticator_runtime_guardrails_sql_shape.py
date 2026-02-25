from pathlib import Path


def test_authenticator_runtime_guardrails_sql_shape() -> None:
    sql = Path(
        "supabase/migrations/20260224_171000_authenticator_runtime_guardrails.sql",
    ).read_text().lower()

    required = [
        "alter role authenticator set pgrst.db_schemas",
        "alter role authenticator set statement_timeout = ''60s''",
        "alter role authenticator set lock_timeout = ''8s''",
        "perform pg_notify('pgrst', 'reload config')",
        "perform pg_notify('pgrst', 'reload schema')",
        "'indicators'",
        "'public'",
    ]

    for item in required:
        assert item in sql
