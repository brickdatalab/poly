import subprocess
from pathlib import Path

import pytest


def _db_url() -> str | None:
    env = {}
    p = Path(".env")
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env.get("SUPABASE_DB_URL")


def _scalar(db_url: str, sql: str) -> str:
    q = sql.strip().rstrip(";")
    return subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", q],
        text=True,
    ).strip()


@pytest.mark.integration
def test_codex_signal_processing_does_not_mutate_indicator_values():
    db_url = _db_url()
    if not db_url:
        pytest.skip("No SUPABASE_DB_URL configured")

    fn_exists = _scalar(
        db_url,
        """
        select count(*)
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname='indicators' and p.proname='fn_process_codex_signal_jobs'
        """,
    )
    if fn_exists == "0":
        pytest.skip("Codex signal functions not applied in DB yet")

    before_count = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.indicator_values
            where bucket_time >= date_trunc('minute', now()) - interval '6 hours'
              and bucket_time < date_trunc('minute', now()) - interval '3 hours'
            """,
        )
    )

    _scalar(
        db_url,
        "select indicators.fn_enqueue_codex_signal_jobs(interval '90 minutes')::text",
    )
    _scalar(
        db_url,
        "select indicators.fn_process_codex_signal_jobs(300)::text",
    )

    after_count = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.indicator_values
            where bucket_time >= date_trunc('minute', now()) - interval '6 hours'
              and bucket_time < date_trunc('minute', now()) - interval '3 hours'
            """,
        )
    )

    assert after_count == before_count
