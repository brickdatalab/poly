#!/usr/bin/env python3
"""Backfill runtime audit/signal evaluation for pair-window ranges."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backfill codex runtime audit rows over a time range")
    ap.add_argument("--from", dest="from_ts", required=True, help="Inclusive UTC timestamptz")
    ap.add_argument("--to", dest="to_ts", required=True, help="Exclusive UTC timestamptz")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD")
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


def main() -> None:
    args = parse_args()
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    if not pairs:
        raise SystemExit("No pairs provided")

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)
    pair_array = ",".join(f"'{p}'" for p in pairs)

    sql = f"""
    with pairs as (
      select unnest(array[{pair_array}]) as pair
    ),
    buckets as (
      select generate_series(
        date_trunc('minute', '{args.from_ts}'::timestamptz),
        date_trunc('minute', '{args.to_ts}'::timestamptz) - interval '15 minutes',
        interval '15 minutes'
      ) as bucket_time
    ),
    run_eval as (
      select p.pair, b.bucket_time, indicators.fn_emit_codex_signals_for_bucket(p.pair, b.bucket_time) as emitted_rows
      from pairs p
      cross join buckets b
    )
    select
      count(*)::int as evaluated_pair_windows,
      coalesce(sum(emitted_rows), 0)::int as total_emitted_rows
    from run_eval;
    """
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-t", "-A", "-c", sql],
        text=True,
    ).strip()
    print(out)


if __name__ == "__main__":
    main()
