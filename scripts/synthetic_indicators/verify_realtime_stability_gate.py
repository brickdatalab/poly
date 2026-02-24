#!/usr/bin/env python3
"""Hard stability gate for realtime signal pipeline."""

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


def check_lag_seconds(db_url: str, sql: str) -> float:
    text = psql_scalar(db_url, sql)
    return float(text or "1e9")


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify realtime signal pipeline stability SLOs")
    ap.add_argument("--raw-trades-max-lag-seconds", type=int, default=90)
    ap.add_argument("--ohlcv-1m-max-lag-seconds", type=int, default=120)
    ap.add_argument("--indicator-values-max-lag-seconds", type=int, default=180)
    ap.add_argument("--audit-lookback-hours", type=int, default=2)
    ap.add_argument("--critical-job-lookback-minutes", type=int, default=60)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    failures: list[str] = []

    raw_lag = check_lag_seconds(
        db_url,
        """
        select coalesce(
          extract(epoch from (now() - min(max_executed_at))),
          1e9
        )
        from (
          select max(executed_at) as max_executed_at
          from public.raw_trades
          where pair in ('BTC-USD','ETH-USD','SOL-USD')
          group by pair
        ) x
        """,
    )
    if raw_lag > args.raw_trades_max_lag_seconds:
        failures.append(
            f"raw_trades lag {raw_lag:.1f}s exceeds {args.raw_trades_max_lag_seconds}s"
        )

    ohlcv_lag = check_lag_seconds(
        db_url,
        """
        select coalesce(
          extract(epoch from (date_trunc('minute', now() at time zone 'utc') - min(max_bucket))),
          1e9
        )
        from (
          select max(bucket_time) as max_bucket
          from indicators.ohlcv_1m
          where pair in ('BTC-USD','ETH-USD','SOL-USD')
          group by pair
        ) x
        """,
    )
    if ohlcv_lag > args.ohlcv_1m_max_lag_seconds:
        failures.append(
            f"ohlcv_1m lag {ohlcv_lag:.1f}s exceeds {args.ohlcv_1m_max_lag_seconds}s"
        )

    iv_lag = check_lag_seconds(
        db_url,
        """
        select coalesce(
          extract(epoch from (date_trunc('minute', now() at time zone 'utc') - min(max_bucket))),
          1e9
        )
        from (
          select max(bucket_time) as max_bucket
          from indicators.indicator_values
          where pair in ('BTC-USD','ETH-USD','SOL-USD')
          group by pair
        ) x
        """,
    )
    if iv_lag > args.indicator_values_max_lag_seconds:
        failures.append(
            f"indicator_values lag {iv_lag:.1f}s exceeds {args.indicator_values_max_lag_seconds}s"
        )

    missing_windows = int(
        psql_scalar(
            db_url,
            f"""
            with pairs as (
              select unnest(array['BTC-USD','ETH-USD','SOL-USD']) as pair
            ),
            buckets as (
              select generate_series(
                date_trunc('hour', now() - interval '{int(args.audit_lookback_hours)} hours'),
                date_trunc('minute', now()) - interval '15 minutes',
                interval '15 minutes'
              ) as bucket_time
            ),
            expected as (
              select p.pair, b.bucket_time
              from pairs p
              cross join buckets b
            )
            select count(*)
            from expected e
            where not exists (
              select 1
              from indicators.codex_signals s
              where s.pair = e.pair
                and s.bucket_time = e.bucket_time
            )
            and not exists (
              select 1
              from indicators.codex_signal_runtime_audit a
              where a.pair = e.pair
                and a.bucket_time = e.bucket_time
            )
            """,
        )
        or "0"
    )
    if missing_windows > 0:
        failures.append(f"missing signal/audit coverage for {missing_windows} pair-windows")

    failed_critical_jobs = int(
        psql_scalar(
            db_url,
            f"""
            select count(*)
            from cron.job_run_details d
            join cron.job j on j.jobid = d.jobid
            where j.jobname in (
              'aggregate-ohlcv-1m',
              'ensure_15m_indicator_jobs',
              'codex-signal-tick-main',
              'codex-signal-tick-retry',
              'raw-trades-freshness-watchdog'
            )
              and d.start_time >= now() - interval '{int(args.critical_job_lookback_minutes)} minutes'
              and d.status = 'failed'
            """,
        )
        or "0"
    )
    if failed_critical_jobs > 0:
        failures.append(f"{failed_critical_jobs} failed critical cron runs in lookback window")

    report = {
        "ok": not failures,
        "thresholds": {
            "raw_trades_max_lag_seconds": args.raw_trades_max_lag_seconds,
            "ohlcv_1m_max_lag_seconds": args.ohlcv_1m_max_lag_seconds,
            "indicator_values_max_lag_seconds": args.indicator_values_max_lag_seconds,
            "audit_lookback_hours": args.audit_lookback_hours,
            "critical_job_lookback_minutes": args.critical_job_lookback_minutes,
        },
        "metrics": {
            "raw_trades_lag_seconds": raw_lag,
            "ohlcv_1m_lag_seconds": ohlcv_lag,
            "indicator_values_lag_seconds": iv_lag,
            "missing_signal_or_audit_windows": missing_windows,
            "failed_critical_job_runs": failed_critical_jobs,
        },
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
