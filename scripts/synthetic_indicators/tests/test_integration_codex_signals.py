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
def test_emit_codex_signals_for_bucket_writes_rows_with_signals_passed():
    db_url = _db_url()
    if not db_url:
        pytest.skip("No SUPABASE_DB_URL configured")

    fn_exists = _scalar(
        db_url,
        """
        select count(*)
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname='indicators' and p.proname='fn_emit_codex_signals_for_bucket'
        """,
    )
    if fn_exists == "0":
        pytest.skip("Codex signal functions not applied in DB yet")

    candidate = _scalar(
        db_url,
        """
        with matched as (
          select s.pair, s.bucket_time
          from indicators.synthetic_indicator_values s
          join indicators.codex_signal_rules r
            on r.is_active
           and r.pair = s.pair
           and r.config_id = s.config_id
          where s.v1 is not null
            and (
              (r.operator='>=' and s.v1 >= r.threshold)
              or
              (r.operator='<=' and s.v1 <= r.threshold)
            )
          order by s.bucket_time desc
          limit 1
        )
        select pair || '|' || bucket_time::text from matched
        """,
    )
    if not candidate:
        pytest.skip("No matched codex rule candidate found")
    pair, bucket_time = candidate.split("|", 1)

    fired = int(
        _scalar(
            db_url,
            f"select indicators.fn_emit_codex_signals_for_bucket('{pair}', '{bucket_time}'::timestamptz)::text",
        )
        or "0"
    )
    assert fired >= 1

    n_rows = int(
        _scalar(
            db_url,
            f"""
            select count(*)
            from indicators.codex_signals
            where pair='{pair}'
              and bucket_time='{bucket_time}'::timestamptz
            """,
        )
    )
    assert n_rows >= 1

    bad_group = int(
        _scalar(
            db_url,
            f"""
            with g as (
              select pair, bucket_time, prediction, count(*)::int as cnt
              from indicators.codex_signals
              where pair='{pair}'
                and bucket_time='{bucket_time}'::timestamptz
              group by 1,2,3
            )
            select count(*)
            from indicators.codex_signals s
            join g using (pair, bucket_time, prediction)
            where s.pair='{pair}'
              and s.bucket_time='{bucket_time}'::timestamptz
              and s.signals_passed <> g.cnt
            """,
        )
    )
    assert bad_group == 0

    bad_minutes = int(
        _scalar(
            db_url,
            f"""
            select count(*)
            from indicators.codex_signals
            where pair='{pair}'
              and bucket_time='{bucket_time}'::timestamptz
              and extract(minute from decision_minute)::int not in (2,17,32,47)
            """,
        )
    )
    assert bad_minutes == 0


@pytest.mark.integration
def test_codex_signal_incremental_queue_runs_without_new_failures():
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

    failed_before = int(
        _scalar(
            db_url,
            "select count(*) from indicators.codex_signal_job_queue where status='failed'",
        )
    )

    _scalar(
        db_url,
        "select indicators.fn_enqueue_codex_signal_jobs(interval '90 minutes')::text",
    )
    processed = int(
        _scalar(
            db_url,
            "select indicators.fn_process_codex_signal_jobs(500)::text",
        )
        or "0"
    )
    assert processed >= 0

    failed_after = int(
        _scalar(
            db_url,
            "select count(*) from indicators.codex_signal_job_queue where status='failed'",
        )
    )
    assert failed_after == failed_before
