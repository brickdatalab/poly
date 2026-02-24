#!/usr/bin/env python3
"""Recover stale realtime pipeline gaps end-to-end.

Workflow:
1) Detect raw_trades lag.
2) Backfill missing trades from Coinbase when lag exceeds threshold.
3) Rebuild OHLCV over recent window.
4) Recompute indicators minute-by-minute over a bounded range.
5) Run realtime signal tick.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PAIRS = ("BTC-USD", "ETH-USD", "SOL-USD")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Recover realtime codex signal pipeline gaps")
    ap.add_argument("--max-lag-seconds", type=int, default=90)
    ap.add_argument("--pairs", default=",".join(PAIRS))
    ap.add_argument("--indicator-lookback-minutes", type=int, default=75)
    ap.add_argument("--ohlcv-lookback-hours", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    return ap.parse_args(argv)


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


def psql_exec(db_url: str, sql: str) -> str:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return out


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    pair_sql = ",".join(f"'{p}'" for p in pairs)

    now_utc = datetime.now(timezone.utc)
    maxes_raw = psql_scalar(
        db_url,
        f"""
        select coalesce(json_object_agg(pair, ts), '{{}}'::json)::text
        from (
          select pair, max(executed_at) as ts
          from public.raw_trades
          where pair in ({pair_sql})
          group by pair
        ) x
        """,
    )
    raw_map: dict[str, str] = json.loads(maxes_raw or "{}")

    lags = {}
    max_lag_seconds = 0.0
    oldest_latest: datetime | None = None
    for p in pairs:
        ts_text = raw_map.get(p)
        if not ts_text:
            lag = 10**9
        else:
            dt = datetime.fromisoformat(ts_text.replace("Z", "+00:00")).astimezone(timezone.utc)
            lag = (now_utc - dt).total_seconds()
            if oldest_latest is None or dt < oldest_latest:
                oldest_latest = dt
        lags[p] = lag
        if lag > max_lag_seconds:
            max_lag_seconds = lag

    report: dict[str, object] = {
        "ran_at_utc": iso_z(now_utc),
        "pairs": pairs,
        "max_lag_seconds": max_lag_seconds,
        "pair_lag_seconds": lags,
        "triggered_backfill": False,
        "steps": [],
    }

    need_recovery = max_lag_seconds > float(args.max_lag_seconds)
    if need_recovery and oldest_latest is not None:
        start = iso_z(oldest_latest + timedelta(seconds=1))
        end = iso_z(datetime.now(timezone.utc))
        cmd = [
            "python3",
            "scripts/backfill_raw_trades_from_coinbase.py",
            "--start",
            start,
            "--end",
            end,
            "--pairs",
            ",".join(pairs),
            "--sleep",
            "0",
            "--limit",
            "100",
        ]
        report["triggered_backfill"] = True
        report["steps"].append({"step": "backfill_raw_trades", "start": start, "end": end, "cmd": cmd})
        if not args.dry_run:
            subprocess.check_call(cmd, cwd=root)

    ohlcv_sql = f"select * from indicators.fn_backfill_ohlcv(interval '{int(args.ohlcv_lookback_hours)} hours');"
    report["steps"].append({"step": "backfill_ohlcv", "sql": ohlcv_sql})
    if not args.dry_run:
        psql_exec(db_url, ohlcv_sql)

    recompute_sql_parts: list[str] = []
    for pair in pairs:
        recompute_sql_parts.append(
            f"""
            with gs as (
              select generate_series(
                date_trunc('minute', now() at time zone 'utc') - interval '{int(args.indicator_lookback_minutes)} minutes',
                date_trunc('minute', now() at time zone 'utc') - interval '1 minute',
                interval '1 minute'
              ) as ts
            )
            select count(*)
            from (
              select (indicators.fn_compute_all_indicators('{pair}'::text, gs.ts, null::text, null::text, null::text)).*
              from gs
            ) x;
            """
        )
    recompute_sql = "\n".join(recompute_sql_parts)
    report["steps"].append({"step": "recompute_indicator_values", "pairs": pairs, "lookback_minutes": args.indicator_lookback_minutes})
    if not args.dry_run:
        psql_exec(db_url, recompute_sql)

    tick_sql = "select indicators.fn_run_realtime_signal_tick(interval '90 minutes', 5000, 10000)::text;"
    report["steps"].append({"step": "run_realtime_tick", "sql": tick_sql})
    if not args.dry_run:
        tick_out = psql_scalar(db_url, tick_sql)
        report["tick_result"] = json.loads(tick_out)

    freshness_sql = f"""
      select json_build_object(
        'raw_trades_max', (select json_object_agg(pair, ts) from (select pair, max(executed_at) as ts from public.raw_trades where pair in ({pair_sql}) group by pair) x),
        'ohlcv_1m_max', (select json_object_agg(pair, ts) from (select pair, max(bucket_time) as ts from indicators.ohlcv_1m where pair in ({pair_sql}) group by pair) x),
        'indicator_values_max', (select json_object_agg(pair, ts) from (select pair, max(bucket_time) as ts from indicators.indicator_values where pair in ({pair_sql}) group by pair) x),
        'synthetic_values_max', (select json_object_agg(pair, ts) from (select pair, max(bucket_time) as ts from indicators.synthetic_indicator_values where pair in ({pair_sql}) group by pair) x),
        'codex_signals_max', (select json_object_agg(pair, ts) from (select pair, max(bucket_time) as ts from indicators.codex_signals where pair in ({pair_sql}) group by pair) x)
      )::text
    """
    report["freshness_after"] = json.loads(psql_scalar(db_url, freshness_sql) or "{}")

    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
