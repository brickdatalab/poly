#!/usr/bin/env python3
"""Create a read-only operational snapshot for OHLCV ingestion health.

This script is reusable for pre/post migration checks. It reads Supabase
credentials from a local .env file, queries Postgres with psql, and writes a
JSON report under scripts/output/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_START = "2026-02-02 00:00:00+00"
DEFAULT_END = "2026-02-08 00:00:00+00"
DEFAULT_PAIRS = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclass(frozen=True)
class DbConfig:
    conninfo: str
    password: str


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into key/value pairs."""
    if not env_path.exists():
        msg = f"Missing env file: {env_path}"
        raise FileNotFoundError(msg)

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def project_ref_from_supabase_url(supabase_url: str) -> str:
    """Extract the project ref from SUPABASE_URL."""
    host = urlparse(supabase_url).netloc
    match = re.match(r"^([a-z0-9]+)\.supabase\.co$", host)
    if not match:
        msg = f"Unable to parse project ref from SUPABASE_URL host: {host}"
        raise ValueError(msg)
    return match.group(1)


def load_db_config(env_path: Path) -> DbConfig:
    """Load DB connection details from env file."""
    env_values = parse_env_file(env_path)
    supabase_url = env_values.get("SUPABASE_URL", "")
    db_password = env_values.get("SUPABASE_DB_PASSWORD", "")
    if not supabase_url or not db_password:
        msg = "SUPABASE_URL and SUPABASE_DB_PASSWORD are required in .env"
        raise ValueError(msg)

    project_ref = project_ref_from_supabase_url(supabase_url)
    conninfo = (
        f"host=db.{project_ref}.supabase.co "
        "port=5432 dbname=postgres user=postgres sslmode=require"
    )
    return DbConfig(conninfo=conninfo, password=db_password)


def run_sql_json(conn: DbConfig, sql: str) -> Any:
    """Run SQL and return decoded JSON payload."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn.password

    wrapped_sql = (
        "with payload as (\n"
        f"{sql}\n"
        ")\n"
        "select coalesce(json_agg(payload), '[]'::json)::text from payload;"
    )

    cmd = [
        "psql",
        conn.conninfo,
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        "--quiet",
        "--command",
        wrapped_sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        msg = f"psql failed ({result.returncode}): {result.stderr.strip()}"
        raise RuntimeError(msg)

    text = result.stdout.strip()
    if not text:
        return []
    return json.loads(text)


def sql_ohlcv_1m_max_by_pair(pairs: tuple[str, ...]) -> str:
    quoted_pairs = ", ".join(f"'{pair}'" for pair in pairs)
    return f"""
    select
      src,
      pair,
      max_bucket
    from (
      select
        'public.ohlcv_1m'::text as src,
        pair,
        max(bucket_time) as max_bucket
      from public.ohlcv_1m
      where pair in ({quoted_pairs})
      group by pair

      union all

      select
        'indicators.ohlcv_1m'::text as src,
        pair,
        max(bucket_time) as max_bucket
      from indicators.ohlcv_1m
      where pair in ({quoted_pairs})
      group by pair
    ) x
    order by src, pair
    """


def sql_missing_minutes(start_ts: str, end_ts: str, pairs: tuple[str, ...]) -> str:
    quoted_pairs = ", ".join(f"'{pair}'" for pair in pairs)
    return f"""
    with params as (
      select
        timestamptz '{start_ts}' as start_ts,
        timestamptz '{end_ts}' as end_ts
    ), expected as (
      select
        pair,
        minute_ts as bucket_time
      from (
        select unnest(array[{quoted_pairs}]) as pair
      ) p
      cross join params
      cross join generate_series(
        params.start_ts,
        params.end_ts - interval '1 minute',
        interval '1 minute'
      ) minute_ts
    ), actual as (
      select distinct pair, bucket_time
      from indicators.ohlcv_1m, params
      where bucket_time >= params.start_ts
        and bucket_time < params.end_ts
        and pair in ({quoted_pairs})
    )
    select
      e.pair,
      count(*)::int as missing_minutes,
      min(e.bucket_time) as first_missing,
      max(e.bucket_time) as last_missing
    from expected e
    left join actual a
      on a.pair = e.pair
     and a.bucket_time = e.bucket_time
    where a.bucket_time is null
    group by e.pair
    order by e.pair
    """


def sql_stream_health() -> str:
    return """
    select
      id,
      service_name,
      last_heartbeat,
      trades_received,
      last_trade_at,
      status,
      error_message,
      updated_at
    from public.websocket_heartbeat
    order by updated_at desc
    limit 1
    """


def sql_raw_trades_latest(pairs: tuple[str, ...]) -> str:
    quoted_pairs = ", ".join(f"'{pair}'" for pair in pairs)
    return f"""
    select
      pair,
      max(executed_at) as max_executed_at,
      count(*)::bigint as trades_total,
      count(*) filter (where executed_at >= now() - interval '1 hour')::bigint as trades_last_hour
    from public.raw_trades
    where pair in ({quoted_pairs})
    group by pair
    order by pair
    """


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"scripts/output/pre_migration_snapshot_{stamp}.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a read-only OHLCV ingestion snapshot")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--start", default=DEFAULT_START, help="Missing-minute window start UTC")
    parser.add_argument("--end", default=DEFAULT_END, help="Missing-minute window end UTC (exclusive)")
    parser.add_argument(
        "--pairs",
        default=",".join(DEFAULT_PAIRS),
        help="Comma-separated pairs (default BTC-USD,ETH-USD,SOL-USD)",
    )
    parser.add_argument("--output", default=None, help="Output JSON path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pair_values = tuple(pair.strip().upper() for pair in args.pairs.split(",") if pair.strip())
    if not pair_values:
        raise ValueError("At least one pair is required")

    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    db = load_db_config(Path(args.env_file))

    snapshot: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_utc": {"start": args.start, "end": args.end},
        "pairs": list(pair_values),
        "ohlcv_1m_max_by_pair": run_sql_json(db, sql_ohlcv_1m_max_by_pair(pair_values)),
        "missing_minutes_by_pair": run_sql_json(db, sql_missing_minutes(args.start, args.end, pair_values)),
        "stream_health": run_sql_json(db, sql_stream_health()),
        "raw_trades_latest_by_pair": run_sql_json(db, sql_raw_trades_latest(pair_values)),
    }

    output_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Snapshot written: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
