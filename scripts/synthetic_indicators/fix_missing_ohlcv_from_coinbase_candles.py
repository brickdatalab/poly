#!/usr/bin/env python3
"""Fill missing indicators.ohlcv_1m rows from Coinbase candles and rebuild 5m/15m.

Notes:
- Coinbase candles API provides OHLCV, not buy/sell split or trade count.
- We preserve volume and split buy/sell 50/50 for missing rows only.
- trade_count is set to 0 for repaired rows.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.exchange.coinbase.com"
DEFAULT_PAIRS = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclass
class GapBlock:
    pair: str
    start: datetime
    end_exclusive: datetime
    missing_minutes: int


def parse_env(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if path.exists():
        for line in path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_db_url(env: dict[str, str]) -> str:
    db_url = (env.get("SUPABASE_DB_URL") or "").strip()
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_csv(db_url: str, sql: str) -> list[dict[str, str]]:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-A", "-F", ",", "--csv", "-c", sql],
        text=True,
    )
    return list(csv.DictReader(out.splitlines()))


def psql_exec(db_url: str, sql: str) -> None:
    subprocess.check_call(["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-c", sql])


def psql_script(db_url: str, script: str) -> None:
    subprocess.run(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off"],
        input=script,
        text=True,
        check=True,
    )


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_gap_blocks(db_url: str, pairs: list[str]) -> list[GapBlock]:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    sql = f"""
    with minmax as (
      select pair, min(bucket_time) mn, max(bucket_time) mx
      from indicators.ohlcv_1m
      where pair in ({pair_sql})
      group by pair
    ), exp as (
      select m.pair, gs as bucket_time
      from minmax m
      cross join lateral generate_series(m.mn, m.mx, interval '1 minute') gs
    ), miss as (
      select e.pair, e.bucket_time
      from exp e
      left join indicators.ohlcv_1m o on o.pair=e.pair and o.bucket_time=e.bucket_time
      where o.bucket_time is null
    ), blocks as (
      select pair, bucket_time,
             bucket_time - (row_number() over (partition by pair order by bucket_time) * interval '1 minute') as grp
      from miss
    )
    select pair,
           min(bucket_time) as gap_start,
           max(bucket_time)+interval '1 minute' as gap_end_exclusive,
           count(*) as missing_minutes
    from blocks
    group by pair, grp
    order by pair, gap_start;
    """
    rows = psql_csv(db_url, sql)
    out: list[GapBlock] = []
    for r in rows:
        out.append(
            GapBlock(
                pair=r["pair"],
                start=parse_iso(r["gap_start"]),
                end_exclusive=parse_iso(r["gap_end_exclusive"]),
                missing_minutes=int(r["missing_minutes"]),
            )
        )
    return out


def fetch_coinbase_candles(product: str, start: datetime, end_exclusive: datetime) -> dict[datetime, dict[str, float]]:
    # Coinbase max 300 candles per request.
    # endpoint start/end are inclusive-ish; we request [start, end_exclusive) by chunking.
    candles: dict[datetime, dict[str, float]] = {}
    cur = start
    while cur < end_exclusive:
        chunk_end = min(cur + timedelta(minutes=300), end_exclusive)
        params = {
            "start": iso_z(cur),
            "end": iso_z(chunk_end),
            "granularity": 60,
        }
        resp = requests.get(
            f"{API_BASE}/products/{product}/candles",
            params=params,
            headers={"User-Agent": "poly-gap-fix/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected candles payload for {product}: {type(payload)}")

        for row in payload:
            # [time, low, high, open, close, volume]
            if not isinstance(row, list) or len(row) < 6:
                continue
            ts = datetime.fromtimestamp(int(row[0]), tz=timezone.utc).replace(second=0, microsecond=0)
            if ts < start or ts >= end_exclusive:
                continue
            low = float(row[1])
            high = float(row[2])
            opn = float(row[3])
            close = float(row[4])
            vol = float(row[5])
            candles[ts] = {
                "open": opn,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
            }

        cur = chunk_end
    return candles


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["pair", "bucket_time", "open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "trade_count"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def load_rows_into_ohlcv_1m(db_url: str, csv_path: Path) -> None:
    script = "\n".join(
        [
            "begin;",
            "create temp table ohlcv_1m_stage (",
            "  pair text not null,",
            "  bucket_time timestamptz not null,",
            "  open numeric not null,",
            "  high numeric not null,",
            "  low numeric not null,",
            "  close numeric not null,",
            "  volume numeric not null,",
            "  buy_volume numeric not null,",
            "  sell_volume numeric not null,",
            "  trade_count integer not null",
            ") on commit drop;",
            f"\\copy ohlcv_1m_stage(pair,bucket_time,open,high,low,close,volume,buy_volume,sell_volume,trade_count) FROM '{csv_path.as_posix()}' CSV HEADER;",
            "insert into indicators.ohlcv_1m(pair,bucket_time,open,high,low,close,volume,buy_volume,sell_volume,trade_count,created_at)",
            "select pair,bucket_time,open,high,low,close,volume,buy_volume,sell_volume,trade_count,now()",
            "from ohlcv_1m_stage",
            "on conflict (pair,bucket_time) do update set",
            "  open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,",
            "  volume=excluded.volume, buy_volume=excluded.buy_volume, sell_volume=excluded.sell_volume,",
            "  trade_count=excluded.trade_count, created_at=now();",
            "commit;",
        ]
    )
    psql_script(db_url, script)


def rebuild_rollups(db_url: str, pairs: list[str], start: datetime, end_exclusive: datetime) -> None:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    start_sql = f"'{iso_z(start)}'::timestamptz"
    end_sql = f"'{iso_z(end_exclusive)}'::timestamptz"

    for tf, step in (("5m", "5 minutes"), ("15m", "15 minutes")):
        table = f"indicators.ohlcv_{tf}"
        sql = f"""
        with src as (
          select
            pair,
            date_trunc('minute', bucket_time)
              - ((extract(minute from bucket_time)::int % {5 if tf=='5m' else 15})::text || ' minutes')::interval
              as bucket_time,
            bucket_time as one_min_bt,
            open, high, low, close, volume, buy_volume, sell_volume, trade_count
          from indicators.ohlcv_1m
          where pair in ({pair_sql})
            and bucket_time >= {start_sql}
            and bucket_time < {end_sql}
        ),
        agg as (
          select
            s.pair,
            s.bucket_time,
            (array_agg(s.open order by s.one_min_bt asc))[1] as open,
            max(s.high) as high,
            min(s.low) as low,
            (array_agg(s.close order by s.one_min_bt desc))[1] as close,
            sum(s.volume) as volume,
            sum(s.buy_volume) as buy_volume,
            sum(s.sell_volume) as sell_volume,
            sum(s.trade_count) as trade_count,
            count(*) as n
          from src s
          group by s.pair, s.bucket_time
        )
        insert into {table}(pair,bucket_time,open,high,low,close,volume,buy_volume,sell_volume,trade_count,created_at)
        select pair,bucket_time,open,high,low,close,volume,buy_volume,sell_volume,trade_count,now()
        from agg
        where n = {5 if tf=='5m' else 15}
        on conflict (pair,bucket_time) do update set
          open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
          volume=excluded.volume, buy_volume=excluded.buy_volume, sell_volume=excluded.sell_volume,
          trade_count=excluded.trade_count, created_at=now();
        """
        psql_exec(db_url, sql)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fix missing ohlcv_1m using Coinbase candles")
    ap.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = parse_env(root / ".env")
    db_url = build_db_url(env)
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]

    gaps = fetch_gap_blocks(db_url, pairs)
    if not gaps:
        print('{"status":"no_gaps"}')
        return

    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    global_start = min(g.start for g in gaps)
    global_end = max(g.end_exclusive for g in gaps)

    for g in gaps:
        candles = fetch_coinbase_candles(g.pair, g.start, g.end_exclusive)
        t = g.start
        while t < g.end_exclusive:
            c = candles.get(t)
            if c is None:
                unresolved.append({"pair": g.pair, "bucket_time": iso_z(t)})
            else:
                vol = float(c["volume"])
                rows.append(
                    {
                        "pair": g.pair,
                        "bucket_time": iso_z(t),
                        "open": f"{c['open']:.10f}",
                        "high": f"{c['high']:.10f}",
                        "low": f"{c['low']:.10f}",
                        "close": f"{c['close']:.10f}",
                        "volume": f"{vol:.10f}",
                        "buy_volume": f"{(vol/2.0):.10f}",
                        "sell_volume": f"{(vol/2.0):.10f}",
                        "trade_count": 0,
                    }
                )
            t += timedelta(minutes=1)

    out_dir = root / "scripts" / "output" / "synthetic_indicators"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = out_dir / f"coinbase_candles_gap_fill_{stamp}.csv"
    write_rows_csv(csv_path, rows)
    if rows:
        load_rows_into_ohlcv_1m(db_url, csv_path)
        rebuild_rollups(db_url, pairs, global_start, global_end)

    report = {
        "status": "ok",
        "pairs": pairs,
        "gap_blocks": [
            {
                "pair": g.pair,
                "start": iso_z(g.start),
                "end_exclusive": iso_z(g.end_exclusive),
                "missing_minutes": g.missing_minutes,
            }
            for g in gaps
        ],
        "rows_prepared": len(rows),
        "rows_unresolved": len(unresolved),
        "csv_path": str(csv_path),
    }
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = out_dir / f"coinbase_candles_gap_fill_{stamp}.json"
    out_path.write_text(__import__("json").dumps(report, indent=2), encoding="utf-8")
    print(__import__("json").dumps(report, indent=2))


if __name__ == "__main__":
    main()
