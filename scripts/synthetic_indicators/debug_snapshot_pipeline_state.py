#!/usr/bin/env python3
"""Capture a reproducible realtime signal pipeline state snapshot.

Outputs JSON with freshness/queue/job state to support root-cause analysis.
"""

from __future__ import annotations

import argparse
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
        raise SystemExit("Missing DB config: need SUPABASE_DB_URL or SUPABASE_URL + SUPABASE_DB_PASSWORD")
    host = supabase_url.replace("https://", "").replace("http://", "").split("/")[0]
    project_ref = host.split(".")[0]
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def psql_scalar(db_url: str, sql: str) -> str:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-t", "-A", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return out.strip()


def psql_json(db_url: str, sql: str) -> object:
    text = psql_scalar(db_url, sql)
    return json.loads(text or "null")


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture codex/synthetic realtime pipeline snapshot")
    ap.add_argument("--out", type=Path, default=None, help="Optional output JSON path")
    ap.add_argument("--recent-runs", type=int, default=150, help="Cron run history rows")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    snapshot = {
        "captured_at_utc": psql_scalar(db_url, "select (now() at time zone 'utc')::text"),
        "raw_trades_max": psql_json(
            db_url,
            """
            select coalesce(json_object_agg(pair, ts), '{}'::json)::text
            from (
              select pair, max(executed_at) as ts
              from public.raw_trades
              where pair in ('BTC-USD','ETH-USD','SOL-USD')
              group by pair
            ) x
            """,
        ),
        "ohlcv_1m_max": psql_json(
            db_url,
            """
            select coalesce(json_object_agg(pair, ts), '{}'::json)::text
            from (
              select pair, max(bucket_time) as ts
              from indicators.ohlcv_1m
              where pair in ('BTC-USD','ETH-USD','SOL-USD')
              group by pair
            ) x
            """,
        ),
        "ohlcv_15m_max": psql_json(
            db_url,
            """
            select coalesce(json_object_agg(pair, ts), '{}'::json)::text
            from (
              select pair, max(bucket_time) as ts
              from indicators.ohlcv_15m
              where pair in ('BTC-USD','ETH-USD','SOL-USD')
              group by pair
            ) x
            """,
        ),
        "indicator_values_max": psql_json(
            db_url,
            """
            select coalesce(json_object_agg(pair, ts), '{}'::json)::text
            from (
              select pair, max(bucket_time) as ts
              from indicators.indicator_values
              where pair in ('BTC-USD','ETH-USD','SOL-USD')
              group by pair
            ) x
            """,
        ),
        "synthetic_values_max": psql_json(
            db_url,
            """
            select coalesce(json_object_agg(pair, ts), '{}'::json)::text
            from (
              select pair, max(bucket_time) as ts
              from indicators.synthetic_indicator_values
              where pair in ('BTC-USD','ETH-USD','SOL-USD')
              group by pair
            ) x
            """,
        ),
        "codex_signals_max": psql_json(
            db_url,
            """
            select coalesce(json_object_agg(pair, ts), '{}'::json)::text
            from (
              select pair, max(bucket_time) as ts
              from indicators.codex_signals
              where pair in ('BTC-USD','ETH-USD','SOL-USD')
              group by pair
            ) x
            """,
        ),
        "cron_jobs": psql_json(
            db_url,
            """
            select coalesce(json_agg(x order by x.jobname), '[]'::json)::text
            from (
              select jobname, schedule, active
              from cron.job
              where jobname in (
                'aggregate-ohlcv-1m',
                'ensure_15m_indicator_jobs',
                'signal-pipeline-01',
                'signal-pipeline-16',
                'signal-pipeline-31',
                'signal-pipeline-46',
                'codex-signal-tick-main',
                'codex-signal-tick-retry',
                'codex-signal-watchdog',
                'raw-trades-freshness-watchdog'
              )
            ) x
            """,
        ),
        "cron_recent_runs": psql_json(
            db_url,
            f"""
            select coalesce(json_agg(x order by x.start_time desc), '[]'::json)::text
            from (
              select j.jobname, d.status, d.start_time, d.end_time,
                     left(coalesce(d.return_message,''), 160) as return_message
              from cron.job_run_details d
              join cron.job j on j.jobid = d.jobid
              where d.start_time >= now() - interval '6 hours'
              order by d.start_time desc
              limit {int(args.recent_runs)}
            ) x
            """,
        ),
        "queue_counts": psql_json(
            db_url,
            """
            select json_build_object(
              'synthetic_pending', (select count(*) from indicators.synthetic_job_queue where status='pending'),
              'synthetic_failed',  (select count(*) from indicators.synthetic_job_queue where status='failed'),
              'codex_pending',     (select count(*) from indicators.codex_signal_job_queue where status='pending'),
              'codex_failed',      (select count(*) from indicators.codex_signal_job_queue where status='failed')
            )::text
            """,
        ),
    }

    text = json.dumps(snapshot, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
