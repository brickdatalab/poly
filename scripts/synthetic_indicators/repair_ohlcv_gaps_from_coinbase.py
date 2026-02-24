#!/usr/bin/env python3
"""Repair missing OHLCV 1m gaps using Coinbase trades, then rebuild OHLCV frames."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class GapWindow:
    start: datetime
    end: datetime  # exclusive


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


def psql_rows(db_url: str, sql: str) -> list[str]:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def to_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def collect_gap_windows(db_url: str, pairs: list[str]) -> list[GapWindow]:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    rows = psql_rows(
        db_url,
        f"""
        with ordered as (
          select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
          from indicators.ohlcv_1m
          where pair in ({pair_sql})
        )
        select (prev_bt + interval '1 minute')::text as gap_start,
               bucket_time::text as gap_end_exclusive
        from ordered
        where prev_bt is not null
          and bucket_time - prev_bt > interval '1 minute'
        order by gap_start
        """,
    )
    windows: list[GapWindow] = []
    for line in rows:
        start_s, end_s = line.split("|")
        windows.append(GapWindow(start=parse_dt(start_s), end=parse_dt(end_s)))
    return windows


def merge_windows(windows: list[GapWindow], merge_if_within_minutes: int) -> list[GapWindow]:
    if not windows:
        return []
    windows = sorted(windows, key=lambda w: w.start)
    merged: list[GapWindow] = [windows[0]]
    pad = timedelta(minutes=merge_if_within_minutes)
    for w in windows[1:]:
        last = merged[-1]
        if w.start <= last.end + pad:
            if w.end > last.end:
                last.end = w.end
        else:
            merged.append(w)
    return merged


def gap_summary(db_url: str, pairs: list[str]) -> dict[str, object]:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    rows = psql_rows(
        db_url,
        f"""
        with ordered as (
          select pair,bucket_time,lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
          from indicators.ohlcv_1m
          where pair in ({pair_sql})
        ), gaps as (
          select pair,
                 ((extract(epoch from bucket_time - prev_bt)/60)::int - 1) as missing_minutes
          from ordered
          where prev_bt is not null
            and bucket_time - prev_bt > interval '1 minute'
        )
        select pair,
               count(*)::int as gap_windows,
               coalesce(sum(missing_minutes),0)::int as missing_minutes_total,
               coalesce(max(missing_minutes),0)::int as largest_gap_minutes
        from gaps
        group by pair
        order by pair
        """,
    )
    out: dict[str, object] = {}
    for r in rows:
        pair, g, m, lg = r.split("|")
        out[pair] = {
            "gap_windows": int(g),
            "missing_minutes_total": int(m),
            "largest_gap_minutes": int(lg),
        }
    return out


def run_backfill_window(root: Path, start: datetime, end: datetime, pairs: list[str]) -> None:
    cmd = [
        "python3",
        "scripts/backfill_raw_trades_from_coinbase.py",
        "--start",
        to_z(start),
        "--end",
        to_z(end),
        "--pairs",
        ",".join(pairs),
        "--sleep",
        "0",
        "--limit",
        "100",
    ]
    subprocess.check_call(cmd, cwd=root)


def main() -> None:
    ap = argparse.ArgumentParser(description="Repair OHLCV gaps using targeted Coinbase backfill windows")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD")
    ap.add_argument("--merge-gap-minutes", type=int, default=2)
    ap.add_argument("--max-windows", type=int, default=0, help="0 means no cap")
    ap.add_argument("--lookback-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]

    before = gap_summary(db_url, pairs)
    windows = collect_gap_windows(db_url, pairs)
    merged = merge_windows(windows, args.merge_gap_minutes)
    if args.max_windows > 0:
        merged = merged[: args.max_windows]

    report: dict[str, object] = {
        "ran_at_utc": to_z(datetime.now(timezone.utc)),
        "pairs": pairs,
        "before": before,
        "raw_windows": len(windows),
        "merged_windows": len(merged),
        "windows": [{"start": to_z(w.start), "end": to_z(w.end)} for w in merged],
        "executed": [],
    }

    if not args.dry_run:
        for i, w in enumerate(merged, start=1):
            run_backfill_window(root, w.start, w.end, pairs)
            report["executed"].append({"index": i, "start": to_z(w.start), "end": to_z(w.end)})

        subprocess.check_call(
            [
                "psql",
                db_url,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"select * from indicators.fn_backfill_ohlcv(interval '{int(args.lookback_days)} days');",
            ],
            cwd=root,
        )

    after = gap_summary(db_url, pairs)
    report["after"] = after

    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
