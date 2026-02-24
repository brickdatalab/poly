#!/usr/bin/env python3
"""
7-day lookback OHLCV completeness report (UTC).

This script reports missing candles per *day* and *pair* for the last N full UTC days
(default 7), across the indicators rollup tables:
  1m, 5m, 10m, 15m, 30m, 45m, 1h, 2h, 6h

Design notes (performance):
- For "missing" counts we use: expected_per_day - count(distinct bucket_time)
  This is much faster than generate_series anti-joins and is usually sufficient
  because bucket_time should be unique per (pair, timeframe, bucket_time).
- If you ever need the *exact missing timestamps*, use the existing exporter:
  /Users/vitolo/Desktop/projects/poly/scripts/export_missing_ohlcv_1m_minutes.py
  (or we can extend this script with a --with-timestamps flag later).

Connection:
- Reads SUPABASE_DB_URL and SUPABASE_DB_PASSWORD from .env (or environment).
- Uses psql via subprocess (no extra Python deps).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


PAIR_ALLOWLIST: Final[tuple[str, ...]] = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclass(frozen=True)
class Row:
    timeframe: str
    day: str  # DD-Mon
    day_sort: str  # YYYY-MM-DD
    btc_missing: int
    eth_missing: int
    sol_missing: int


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        os.environ.setdefault(k, v)


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def psql_json(db_url: str, db_password: str, sql: str, timeout_s: int = 45) -> Any:
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")
    cmd = ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", sql]
    out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=timeout_s)
    s = out.decode("utf-8", errors="replace").strip()
    return None if not s else json.loads(s)


def build_sql(days: int) -> str:
    """
    Return a single query that outputs JSON rows:
      [{timeframe, day, day_sort, btc_missing, eth_missing, sol_missing}, ...]
    """
    # Expected candles per full UTC day:
    # 1m: 1440, 5m: 288, 10m: 144, 15m: 96, 30m: 48, 45m: 32, 1h: 24, 2h: 12, 6h: 4
    # NOTE: We intentionally report the last N *full* UTC days (exclude current partial day).
    pairs_sql = ",".join([f"'{p}'" for p in PAIR_ALLOWLIST])
    return f"""
    with bounds as (
      select
        date_trunc('day', now() at time zone 'UTC')::timestamptz as end_ts,
        (date_trunc('day', now() at time zone 'UTC') - interval '{days} days')::timestamptz as start_ts
    ),
    days as (
      select generate_series(
        (select start_ts from bounds)::date,
        ((select end_ts from bounds)::date - 1),
        interval '1 day'
      )::date as day
    ),
    pairs as (
      select unnest(array[{pairs_sql}]::text[]) as pair
    ),
    timeframes as (
      select * from (values
        ('1m',  1440, 'indicators.ohlcv_1m'::text),
        ('5m',   288, 'indicators.ohlcv_5m'::text),
        ('10m',  144, 'indicators.ohlcv_10m'::text),
        ('15m',   96, 'indicators.ohlcv_15m'::text),
        ('30m',   48, 'indicators.ohlcv_30m'::text),
        ('45m',   32, 'indicators.ohlcv_45m'::text),
        ('1h',    24, 'indicators.ohlcv_1h'::text),
        ('2h',    12, 'indicators.ohlcv_2h'::text),
        ('6h',     4, 'indicators.ohlcv_6h'::text)
      ) as t(timeframe, expected_per_day, table_name)
    ),
    counts as (
      -- Unrolled UNION ALL (planner-friendly, avoids dynamic SQL)
      select '1m'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_1m, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '5m'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_5m, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '10m'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_10m, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '15m'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_15m, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '30m'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_30m, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '45m'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_45m, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '1h'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_1h, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '2h'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_2h, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
      union all
      select '6h'::text as timeframe, pair, (bucket_time at time zone 'UTC')::date as day, count(distinct bucket_time)::int as n
      from indicators.ohlcv_6h, bounds
      where bucket_time >= bounds.start_ts and bucket_time < bounds.end_ts and pair = any(array[{pairs_sql}]::text[])
      group by 1,2,3
    ),
    grid as (
      select d.day, p.pair, tf.timeframe, tf.expected_per_day
      from days d
      cross join pairs p
      cross join timeframes tf
    ),
    missing as (
      select
        g.timeframe,
        g.day,
        g.pair,
        greatest(0, g.expected_per_day - coalesce(c.n, 0))::int as missing
      from grid g
      left join counts c
        on c.timeframe = g.timeframe and c.pair = g.pair and c.day = g.day
    )
    select jsonb_agg(row_to_json(t) order by t.timeframe, t.day_sort desc)
    from (
      select
        timeframe,
        to_char(day, 'DD-Mon') as day,
        day::text as day_sort,
        max(missing) filter (where pair='BTC-USD') as btc_missing,
        max(missing) filter (where pair='ETH-USD') as eth_missing,
        max(missing) filter (where pair='SOL-USD') as sol_missing
      from missing
      group by timeframe, day
      order by timeframe, day desc
    ) t;
    """


def parse_rows(raw: list[dict[str, Any]] | None) -> list[Row]:
    rows: list[Row] = []
    for r in raw or []:
        rows.append(
            Row(
                timeframe=str(r["timeframe"]),
                day=str(r["day"]),
                day_sort=str(r["day_sort"]),
                btc_missing=int(r["btc_missing"]),
                eth_missing=int(r["eth_missing"]),
                sol_missing=int(r["sol_missing"]),
            )
        )
    return rows


def print_table(rows: list[Row], timeframe: str) -> None:
    tf_rows = [r for r in rows if r.timeframe == timeframe]
    print(f"\n{timeframe} missing candles (last 7 full UTC days)\n")
    print("| Day | BTC missing | ETH missing | SOL missing |")
    print("|---|---:|---:|---:|")
    for r in tf_rows:
        print(f"| {r.day} | {r.btc_missing} | {r.eth_missing} | {r.sol_missing} |")


def main() -> int:
    parser = argparse.ArgumentParser(description="OHLCV completeness report (last N full UTC days)")
    parser.add_argument("--days", type=int, default=7, help="number of full UTC days to look back (default: 7)")
    parser.add_argument(
        "--tldr",
        action="store_true",
        help="only print a TLDR summary (non-zero findings); still writes JSON output",
    )
    args = parser.parse_args()

    load_dotenv(Path("/Users/vitolo/Desktop/projects/poly/.env"))
    db_url = require_env("SUPABASE_DB_URL")
    db_password = require_env("SUPABASE_DB_PASSWORD")

    sql = build_sql(days=args.days)
    raw = psql_json(db_url, db_password, sql, timeout_s=60)
    rows = parse_rows(raw)

    # Persist JSON output for later reference
    out_dir = Path("/Users/vitolo/Desktop/projects/poly/scripts/output/missing_reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"missing_ohlcv_{args.days}d_{ts}.json"
    out_path.write_text(json.dumps([r.__dict__ for r in rows], indent=2, sort_keys=True) + "\n")

    nonzero = [r for r in rows if (r.btc_missing + r.eth_missing + r.sol_missing) > 0]
    if args.tldr:
        if not nonzero:
            print(f"TLDR: No missing candles in any timeframe for last {args.days} full UTC days.")
        else:
            print(f"TLDR: Missing candles detected ({len(nonzero)} day/timeframe rows).")
            for r in nonzero:
                print(
                    f"- {r.timeframe} {r.day_sort}: BTC={r.btc_missing} ETH={r.eth_missing} SOL={r.sol_missing}"
                )
        print(f"\nReport JSON: {out_path}")
        return 1 if nonzero else 0

    # Full report: tables per timeframe, in order
    for tf in ("1m", "5m", "10m", "15m", "30m", "45m", "1h", "2h", "6h"):
        print_table(rows, tf)

    if not nonzero:
        print(f"\nOnly: none (no missing candles) in the last {args.days} full UTC days.")
    else:
        print(f"\nNon-zero rows: {len(nonzero)} (see TLDR with --tldr)")
    print(f"\nReport JSON: {out_path}")
    return 1 if nonzero else 0


if __name__ == "__main__":
    raise SystemExit(main())

