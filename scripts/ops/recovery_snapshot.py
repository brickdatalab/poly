#!/usr/bin/env python3
"""Capture indicator pipeline recovery snapshot for incident auditing."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def load_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_db_url(env: dict[str, str]) -> str:
    direct = (env.get("SUPABASE_DB_URL") or "").strip()
    if direct:
        return direct
    supabase_url = (env.get("SUPABASE_URL") or "").strip()
    password = (env.get("SUPABASE_DB_PASSWORD") or "").strip()
    if not supabase_url or not password:
        raise SystemExit("Missing DB config: set SUPABASE_DB_URL or SUPABASE_URL + SUPABASE_DB_PASSWORD")
    host = supabase_url.replace("https://", "").replace("http://", "").split("/")[0]
    project_ref = host.split(".")[0]
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def psql_scalar(db_url: str, sql: str) -> str:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-t", "-A", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return out.strip()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    sql = """
      select json_build_object(
        'captured_at_utc', (now() at time zone 'utc'),
        'authenticator_rolconfig', (select rolconfig from pg_roles where rolname='authenticator'),
        'worker_queue_counts', (
          select json_object_agg(status, n)
          from (
            select status, count(*)::int as n
            from indicators.job_queue
            group by status
          ) q
        ),
        'freshness', (
          select json_build_object(
            'ohlcv_1m', (select max(bucket_time) from indicators.ohlcv_1m),
            'ohlcv_5m', (select max(bucket_time) from indicators.ohlcv_5m),
            'ohlcv_15m', (select max(bucket_time) from indicators.ohlcv_15m),
            'indicator_values', (select max(bucket_time) from indicators.indicator_values),
            'open_interest', (select max(bucket_time) from indicators.open_interest),
            'oi_features', (select max(bucket_time) from indicators.oi_features),
            'order_book_indicators', (select max(captured_at) from indicators.order_book_indicators)
          )
        )
      )::text;
    """
    print(json.dumps(json.loads(psql_scalar(db_url, sql)), indent=2))


if __name__ == "__main__":
    main()

