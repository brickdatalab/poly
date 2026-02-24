#!/usr/bin/env python3
"""Export missing 1-minute OHLCV timestamps for selected pairs.

This script is intentionally reusable as part of the local scripts template bank.
It reads Supabase credentials from a local .env file and queries Postgres via psql,
then writes a CSV containing every missing UTC minute for each requested pair.

Default window is the outage-analysis window used in this project:
  start: 2026-02-02 00:00:00+00
  end:   2026-02-08 00:00:00+00 (end-exclusive)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_START = "2026-02-02 00:00:00+00"
DEFAULT_END = "2026-02-08 00:00:00+00"
DEFAULT_PAIRS = ["BTC-USD", "ETH-USD", "SOL-USD"]


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse key/value lines from .env while ignoring comments and blank lines."""
    if not env_path.exists():
        raise FileNotFoundError(f"Missing env file: {env_path}")

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        values[key] = val
    return values


def project_ref_from_supabase_url(supabase_url: str) -> str:
    """Extract the Supabase project ref from SUPABASE_URL.

    Example:
      https://cxvntzszdkyggjjenefn.supabase.co -> cxvntzszdkyggjjenefn
    """
    parsed = urlparse(supabase_url)
    host = parsed.netloc
    if not host:
        raise ValueError("SUPABASE_URL is invalid or empty")

    match = re.match(r"^([a-z0-9]+)\.supabase\.co$", host)
    if not match:
        raise ValueError(f"Unable to parse project ref from SUPABASE_URL host: {host}")
    return match.group(1)


def build_missing_minutes_sql(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    """Build SQL that returns missing minute timestamps by pair (UTC)."""
    quoted_pairs = ", ".join(f"'{p}'" for p in pairs)

    # We generate expected minutes for each pair, then anti-join against actual rows.
    return f"""
with params as (
  select
    timestamptz '{start_ts}' as start_ts,
    timestamptz '{end_ts}' as end_ts
),
pairs as (
  select unnest(array[{quoted_pairs}]) as pair
),
expected as (
  select
    p.pair,
    gs.minute_ts as bucket_time
  from pairs p
  cross join params
  cross join generate_series(
    params.start_ts,
    params.end_ts - interval '1 minute',
    interval '1 minute'
  ) as gs(minute_ts)
),
actual as (
  select distinct
    pair,
    bucket_time
  from indicators.ohlcv_1m, params
  where bucket_time >= params.start_ts
    and bucket_time < params.end_ts
    and pair = any(array[{quoted_pairs}])
),
missing as (
  select
    e.pair,
    e.bucket_time
  from expected e
  left join actual a
    on a.pair = e.pair
   and a.bucket_time = e.bucket_time
  where a.bucket_time is null
)
select
  pair,
  to_char(bucket_time at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as missing_utc
from missing
order by pair, bucket_time;
""".strip()


def run_psql_query(conninfo: str, password: str, sql: str) -> str:
    """Execute SQL via psql and return CSV text output."""
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    cmd = [
        "psql",
        conninfo,
        "--no-psqlrc",
        "--csv",
        "--quiet",
        "--command",
        sql,
    ]

    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed with code {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def write_csv(output_path: Path, csv_text: str) -> int:
    """Write CSV output and return row count excluding header."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(csv_text, encoding="utf-8")

    # Count data rows without reparsing SQL output elsewhere.
    with output_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    return max(len(rows) - 1, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export missing OHLCV 1m UTC timestamps by pair")
    parser.add_argument("--env-file", default=".env", help="Path to .env file (default: .env)")
    parser.add_argument("--start", default=DEFAULT_START, help="Start timestamp UTC, inclusive")
    parser.add_argument("--end", default=DEFAULT_END, help="End timestamp UTC, exclusive")
    parser.add_argument(
        "--pairs",
        default=",".join(DEFAULT_PAIRS),
        help="Comma-separated pairs (default: BTC-USD,ETH-USD,SOL-USD)",
    )
    parser.add_argument(
        "--output",
        default="scripts/output/missing_ohlcv_1m_minutes_2026-02-02_to_2026-02-08_utc.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    env_values = parse_env_file(Path(args.env_file))
    supabase_url = env_values.get("SUPABASE_URL", "")
    db_password = env_values.get("SUPABASE_DB_PASSWORD", "")
    if not supabase_url or not db_password:
        raise ValueError("SUPABASE_URL and SUPABASE_DB_PASSWORD are required in .env")

    project_ref = project_ref_from_supabase_url(supabase_url)
    conninfo = (
        f"host=db.{project_ref}.supabase.co "
        f"port=5432 dbname=postgres user=postgres sslmode=require"
    )

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    if not pairs:
        raise ValueError("At least one pair must be provided")

    sql = build_missing_minutes_sql(start_ts=args.start, end_ts=args.end, pairs=pairs)
    csv_text = run_psql_query(conninfo=conninfo, password=db_password, sql=sql)
    row_count = write_csv(Path(args.output), csv_text)

    print(f"Output file: {Path(args.output).resolve()}")
    print(f"Pairs: {', '.join(pairs)}")
    print(f"Window UTC: [{args.start}, {args.end})")
    print(f"Missing rows exported: {row_count}")


if __name__ == "__main__":
    main()
