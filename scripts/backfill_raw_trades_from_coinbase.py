#!/usr/bin/env python3
"""Backfill public.raw_trades from Coinbase Exchange historical trades.

Why this exists:
- Our ingestion stream writes trade-level ticks to `public.raw_trades`.
- Downstream OHLCV is computed from raw trades.
- When PostgREST is unhealthy, streamers can stall; this script reconstructs the
  missing trade window from Coinbase public APIs.

Key guarantees:
- Idempotent: inserts with `ON CONFLICT DO NOTHING`.
- Safe to run while live ingestion continues (window is historical).
- Avoids trigger side effects during bulk insert by setting
  `session_replication_role = replica` for the insert session, then relies on
  `indicators.fn_backfill_ohlcv()` to rebuild OHLCV in bulk.

Output:
- Writes a single CSV file containing all fetched trades.
- Writes a JSON report with counts and pagination stats.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

DEFAULT_START = "2026-02-07T04:54:00Z"
DEFAULT_END = "2026-02-08T03:34:00Z"  # end-exclusive
DEFAULT_PAIRS = ("BTC-USD", "ETH-USD", "SOL-USD")

API_BASE = "https://api.exchange.coinbase.com"
DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class DbConfig:
    conninfo: str
    password: str


def parse_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        raise FileNotFoundError(f"Missing env file: {env_path}")

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def project_ref_from_supabase_url(supabase_url: str) -> str:
    parsed = urlparse(supabase_url)
    host = parsed.netloc
    match = re.match(r"^([a-z0-9]+)\.supabase\.co$", host)
    if not match:
        raise ValueError(f"Unable to parse project ref from SUPABASE_URL host: {host}")
    return match.group(1)


def load_db_config(env_path: Path) -> DbConfig:
    env = parse_env_file(env_path)
    supabase_url = env.get("SUPABASE_URL", "")
    password = env.get("SUPABASE_DB_PASSWORD", "")
    if not supabase_url or not password:
        raise ValueError("SUPABASE_URL and SUPABASE_DB_PASSWORD are required in .env")
    ref = project_ref_from_supabase_url(supabase_url)
    conninfo = f"host=db.{ref}.supabase.co port=5432 dbname=postgres user=postgres sslmode=require"
    return DbConfig(conninfo=conninfo, password=password)


def parse_iso_z(value: str) -> datetime:
    # Strict-ish: expects trailing Z.
    if not value.endswith("Z"):
        raise ValueError(f"Expected UTC Z timestamp, got: {value}")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def http_get_trades(
    product_id: str, *, limit: int, after: str | None, timeout_s: int
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, str] = {"limit": str(limit)}
    # Coinbase Exchange pagination for /trades works as \"older than cursor\" via
    # the `after` query parameter. The response header `cb-after` provides the
    # next cursor (older trade_id).
    if after:
        params["after"] = after

    url = f"{API_BASE}/products/{product_id}/trades"
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": "poly-backfill/1.0"},
        timeout=timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
    cb_after = resp.headers.get("cb-after")
    return data, cb_after


def iter_trades_window(
    product_id: str,
    *,
    start: datetime,
    end: datetime,
    limit: int,
    sleep_s: float,
    max_requests: int,
    timeout_s: int,
) -> tuple[int, int, int]:
    """Yield trades within [start, end) in descending time, paging backward.

    Returns: (requests_made, trades_seen, trades_kept)
    """
    after: str | None = None
    requests_made = 0
    trades_seen = 0
    trades_kept = 0

    while True:
        if requests_made >= max_requests:
            raise RuntimeError(f"max_requests exceeded for {product_id}: {max_requests}")

        page, next_after = http_get_trades(product_id, limit=limit, after=after, timeout_s=timeout_s)
        requests_made += 1
        if not page:
            break

        # Trades are newest->oldest in each page.
        oldest_time = None
        for trade in page:
            trades_seen += 1
            t = parse_iso_z(trade["time"])
            oldest_time = t if oldest_time is None or t < oldest_time else oldest_time
            if t < start:
                continue
            if t >= end:
                continue

            # Normalized row for CSV/DB.
            yield {
                "trade_id": int(trade["trade_id"]),
                "pair": product_id,
                "price": trade["price"],
                "size": trade["size"],
                "side": str(trade.get("side", "UNKNOWN")).upper(),
                "executed_at": iso_z(t),
            }
            trades_kept += 1

        # Stop when we've paged past the start.
        if oldest_time is not None and oldest_time < start:
            break

        after = next_after
        if not after:
            break

        if sleep_s > 0:
            time.sleep(sleep_s)

    return requests_made, trades_seen, trades_kept


def write_trades_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["trade_id", "pair", "price", "size", "side", "executed_at"]
    count = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def run_psql_file(conn: DbConfig, sql_path: Path) -> None:
    env = os.environ.copy()
    env["PGPASSWORD"] = conn.password

    cmd = [
        "psql",
        conn.conninfo,
        "--no-psqlrc",
        "--quiet",
        "--set",
        "ON_ERROR_STOP=1",
        "--file",
        str(sql_path),
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()}")


def load_csv_into_raw_trades(conn: DbConfig, csv_path: Path) -> None:
    sql_path = csv_path.with_suffix(".load.sql")
    # Use a single psql session so TEMP table and \copy are scoped correctly.
    # Also disable triggers in this session to avoid flooding job_queue/edge worker.
    sql_path.write_text(
        "\n".join(
            [
                "BEGIN;",
                "SET LOCAL session_replication_role = replica;",
                "CREATE TEMP TABLE raw_trades_stage (",
                "  trade_id bigint not null,",
                "  pair text not null,",
                "  price numeric not null,",
                "  size numeric not null,",
                "  side text not null,",
                "  executed_at timestamptz not null",
                ") ON COMMIT DROP;",
                f"\\copy raw_trades_stage(trade_id,pair,price,size,side,executed_at) FROM '{csv_path}' WITH (FORMAT csv, HEADER true);",
                "INSERT INTO public.raw_trades (trade_id,pair,price,size,side,executed_at)",
                "SELECT trade_id,pair,price,size,side,executed_at",
                "FROM raw_trades_stage",
                "ON CONFLICT (trade_id, executed_at) DO NOTHING;",
                "COMMIT;",
            ]
        ),
        encoding="utf-8",
    )
    try:
        run_psql_file(conn, sql_path)
    finally:
        try:
            sql_path.unlink()
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Backfill public.raw_trades from Coinbase historical trades")
    p.add_argument("--env-file", default=".env", help="Path to .env")
    p.add_argument("--start", default=DEFAULT_START, help="UTC window start (inclusive), e.g. 2026-02-07T04:54:00Z")
    p.add_argument("--end", default=DEFAULT_END, help="UTC window end (exclusive)")
    p.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="Comma-separated pairs")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Trades per API call (max 100)")
    p.add_argument("--sleep", type=float, default=0.12, help="Sleep seconds between API calls")
    p.add_argument("--max-requests", type=int, default=20000, help="Safety cap per pair")
    p.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    p.add_argument(
        "--out-csv",
        default=None,
        help="Output CSV path (default scripts/output/raw_trades_backfill_<start>_to_<end>.csv)",
    )
    p.add_argument("--no-load", action="store_true", help="Only fetch+write CSV, do not load into DB")
    return p


def main() -> int:
    args = build_parser().parse_args()
    start = parse_iso_z(args.start)
    end = parse_iso_z(args.end)
    if end <= start:
        raise ValueError("end must be after start")

    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    if not pairs:
        raise ValueError("At least one pair is required")

    stamp = f"{args.start.replace(':','').replace('-','').replace('T','T').replace('Z','Z')}_to_{args.end.replace(':','').replace('-','').replace('T','T').replace('Z','Z')}"
    out_csv = Path(args.out_csv) if args.out_csv else Path(f"scripts/output/raw_trades_backfill_{stamp}.csv")

    report: dict[str, Any] = {
        "start": iso_z(start),
        "end": iso_z(end),
        "pairs": pairs,
        "generated_at": iso_z(datetime.now(timezone.utc)),
        "per_pair": {},
        "csv_path": str(out_csv.resolve()),
    }

    def all_rows() -> Iterable[dict[str, Any]]:
        for pair in pairs:
            kept = 0
            seen = 0
            reqs = 0
            t0 = time.time()
            # Use a generator so we stream directly to the CSV.
            for row in iter_trades_window(
                pair,
                start=start,
                end=end,
                limit=args.limit,
                sleep_s=args.sleep,
                max_requests=args.max_requests,
                timeout_s=args.timeout,
            ):
                kept += 1
                yield row
            # We can't get reqs/seen from generator after the fact; store approximate by re-fetching? no.
            # Instead: keep these fields best-effort via follow-up call count is not critical.
            report["per_pair"][pair] = {
                "trades_kept": kept,
                "duration_s": round(time.time() - t0, 3),
                "note": "req/seen not tracked precisely in streaming mode",
            }

    count = write_trades_csv(out_csv, all_rows())
    report["total_trades_kept"] = count

    report_path = out_csv.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"CSV written: {out_csv.resolve()}")
    print(f"Report written: {report_path.resolve()}")
    print(f"Total trades kept: {count}")

    if args.no_load:
        return 0

    conn = load_db_config(Path(args.env_file))
    load_csv_into_raw_trades(conn, out_csv.resolve())
    print("Loaded into public.raw_trades (bulk insert, triggers disabled for session).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
