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
def test_eth_window_edge_synthetic_populates_for_eth_only():
    db_url = _db_url()
    if not db_url:
        pytest.skip("No SUPABASE_DB_URL configured")

    fn_exists = _scalar(
        db_url,
        """
        select count(*)
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname='indicators' and p.proname='fn_compute_synthetic_window_edge_eth_nonrolling'
        """,
    )
    if fn_exists == "0":
        pytest.skip("ETH window-edge synthetic function not applied yet")

    _scalar(
        db_url,
        """
        select indicators.fn_backfill_synthetic_indicators(
          date_trunc('minute', now()) - interval '2 hours',
          date_trunc('minute', now()) - interval '15 minutes',
          array['BTC-USD','ETH-USD','SOL-USD']
        )::text
        """,
    )

    eth_rows = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.synthetic_indicator_values
            where pair='ETH-USD'
              and config_id='syn_window_edge_57to01_eth_nonrolling_tplus2'
              and bucket_time >= date_trunc('minute', now()) - interval '2 hours'
            """,
        )
    )
    assert eth_rows >= 1

    btc_rows = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.synthetic_indicator_values
            where pair='BTC-USD'
              and config_id='syn_window_edge_57to01_eth_nonrolling_tplus2'
              and bucket_time >= date_trunc('minute', now()) - interval '2 hours'
            """,
        )
    )
    sol_rows = int(
        _scalar(
            db_url,
            """
            select count(*)
            from indicators.synthetic_indicator_values
            where pair='SOL-USD'
              and config_id='syn_window_edge_57to01_eth_nonrolling_tplus2'
              and bucket_time >= date_trunc('minute', now()) - interval '2 hours'
            """,
        )
    )
    assert btc_rows == 0
    assert sol_rows == 0
