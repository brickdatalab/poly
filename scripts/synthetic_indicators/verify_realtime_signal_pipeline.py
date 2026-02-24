#!/usr/bin/env python3
"""Operational verification for realtime synthetic/codex signal pipeline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_JOBS = (
    "codex-signal-tick-main",
    "codex-signal-tick-retry",
    "codex-signal-watchdog",
)


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


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify realtime signal pipeline scheduler and freshness")
    ap.add_argument("--max-lag-minutes", type=int, default=20)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    now_text = psql_scalar(db_url, "select (now() at time zone 'utc')::text")
    now_utc = datetime.fromisoformat(now_text).replace(tzinfo=timezone.utc)

    jobs_json = psql_scalar(
        db_url,
        """
        select coalesce(json_agg(x), '[]'::json)::text
        from (
          select jobname, schedule, active
          from cron.job
          where jobname in ('codex-signal-tick-main','codex-signal-tick-retry','codex-signal-watchdog')
          order by jobname
        ) x
        """,
    )
    jobs = json.loads(jobs_json or "[]")
    job_names = {j["jobname"] for j in jobs}

    latest_json = psql_scalar(
        db_url,
        """
        select json_build_object(
          'latest_synth', (select max(bucket_time) from indicators.synthetic_indicator_values where pair in ('BTC-USD','ETH-USD')),
          'latest_queue', (select max(bucket_time) from indicators.codex_signal_job_queue where pair in ('BTC-USD','ETH-USD')),
          'latest_signals', (select max(bucket_time) from indicators.codex_signals where pair in ('BTC-USD','ETH-USD')),
          'latest_main_run', (
            select max(d.start_time)
            from cron.job_run_details d
            join cron.job j on j.jobid = d.jobid
            where j.jobname = 'codex-signal-tick-main'
          )
        )::text
        """,
    )
    latest = json.loads(latest_json or "{}")

    failures: list[str] = []
    missing_jobs = [name for name in REQUIRED_JOBS if name not in job_names]
    if missing_jobs:
        failures.append(f"Missing cron jobs: {', '.join(missing_jobs)}")
    inactive_jobs = [j["jobname"] for j in jobs if not j.get("active")]
    if inactive_jobs:
        failures.append(f"Inactive cron jobs: {', '.join(inactive_jobs)}")

    def check_lag(key: str) -> None:
        ts = latest.get(key)
        if not ts:
            failures.append(f"{key} is null")
            return
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        lag_min = (now_utc - dt).total_seconds() / 60.0
        if lag_min > args.max_lag_minutes:
            failures.append(f"{key} lag too high: {lag_min:.2f}m > {args.max_lag_minutes}m")

    check_lag("latest_synth")
    check_lag("latest_queue")
    check_lag("latest_main_run")

    report = {
        "now_utc": now_utc.isoformat(),
        "max_lag_minutes": args.max_lag_minutes,
        "jobs": jobs,
        "latest": latest,
        "ok": not failures,
        "failures": failures,
    }
    print(json.dumps(report, indent=2))

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
