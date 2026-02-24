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
def test_new_candidate_synthetics_compute_and_emit_signals():
    db_url = _db_url()
    if not db_url:
        pytest.skip("No SUPABASE_DB_URL configured")

    fn_exists = _scalar(
        db_url,
        """
        select count(*)
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname='indicators' and p.proname='fn_compute_synthetic_cvd_price_divergence_velocity'
        """,
    )
    if fn_exists == "0":
        pytest.skip("New candidate synthetic functions not applied in DB yet")

    _scalar(
        db_url,
        """
        with bounds as (
          select
            (date_trunc('hour', now()) + floor(extract(minute from now()) / 15) * interval '15 minutes') as aligned_now
        )
        select indicators.fn_backfill_synthetic_indicators(
          (select aligned_now - interval '6 hours' from bounds),
          (select aligned_now - interval '15 minutes' from bounds),
          array['BTC-USD','ETH-USD','SOL-USD']
        )::text
        """,
    )

    n_cvd = int(
        _scalar(
            db_url,
            """
            with bounds as (
              select
                (date_trunc('hour', now()) + floor(extract(minute from now()) / 15) * interval '15 minutes') as aligned_now
            )
            select count(*)
            from indicators.synthetic_indicator_values
            where config_id='syn_cvd_price_divergence_velocity_15m5_tplus2'
              and bucket_time >= (select aligned_now - interval '6 hours' from bounds)
            """,
        )
    )
    n_mtc = int(
        _scalar(
            db_url,
            """
            with bounds as (
              select
                (date_trunc('hour', now()) + floor(extract(minute from now()) / 15) * interval '15 minutes') as aligned_now
            )
            select count(*)
            from indicators.synthetic_indicator_values
            where config_id='syn_multitimeframe_trend_confluence_tplus2'
              and bucket_time >= (select aligned_now - interval '6 hours' from bounds)
            """,
        )
    )
    assert n_cvd >= 3
    assert n_mtc >= 3

    _scalar(
        db_url,
        "select indicators.fn_enqueue_codex_signal_jobs(interval '6 hours')::text",
    )
    _scalar(
        db_url,
        "select indicators.fn_process_codex_signal_jobs(1000)::text",
    )

    n_rules_total = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.codex_signal_rules
            where config_id in (
              'syn_cvd_price_divergence_velocity_15m5_tplus2',
              'syn_multitimeframe_trend_confluence_tplus2'
            )
            """,
        )
    )
    assert n_rules_total == 12

    n_rules_active = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.codex_signal_rules
            where config_id in (
              'syn_cvd_price_divergence_velocity_15m5_tplus2',
              'syn_multitimeframe_trend_confluence_tplus2'
            ) and is_active
            """,
        )
    )
    assert n_rules_active >= 1

    n_sig = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.codex_signals
            where rule_id like '%syn_cvd_div_15m5%'
               or rule_id like '%syn_mtc_%'
            """,
        )
    )
    assert n_sig >= 1
