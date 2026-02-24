#!/usr/bin/env python3
"""Repair missing OHLCV buckets in indicators schema.

Strategy:
1) Detect missing 1m buckets between each pair's min/max bucket_time.
2) Fill missing 1m rows using last-known close (or next open fallback) with zero volume/trades.
3) Rebuild higher OHLCV rollups from repaired 1m data.
4) Emit before/after gap summaries for all OHLCV tables.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from math import floor

TF_TABLES: tuple[tuple[str, str], ...] = (
    ("ohlcv_1m", "1 minute"),
    ("ohlcv_5m", "5 minutes"),
    ("ohlcv_10m", "10 minutes"),
    ("ohlcv_15m", "15 minutes"),
    ("ohlcv_30m", "30 minutes"),
    ("ohlcv_45m", "45 minutes"),
    ("ohlcv_1h", "1 hour"),
    ("ohlcv_2h", "2 hours"),
    ("ohlcv_6h", "6 hours"),
    ("ohlcv_12h", "12 hours"),
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


def psql_rows(db_url: str, sql: str) -> list[str]:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-t", "-A", "-F", "|", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def psql_exec(db_url: str, sql: str) -> str:
    return subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-c", sql.strip().rstrip(";")],
        text=True,
    )


def psql_scalar(db_url: str, sql: str) -> str:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-t", "-A", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return out.strip()


def quote_ts(ts: str | None) -> str:
    if ts is None:
        return "null::timestamptz"
    escaped = ts.replace("'", "''")
    return f"'{escaped}'::timestamptz"


def gap_summary_sql(table: str, step_interval: str, pair_sql: str, summary_start: str | None) -> str:
    start_clause = f"and bucket_time >= {quote_ts(summary_start)}" if summary_start else ""
    return f"""
    with ordered as (
      select pair, bucket_time, lag(bucket_time) over(partition by pair order by bucket_time) as prev_bt
      from indicators.{table}
      where pair in ({pair_sql})
        {start_clause}
    ), gaps as (
      select
        pair,
        ((extract(epoch from bucket_time - prev_bt) / extract(epoch from interval '{step_interval}'))::int - 1) as missing_steps
      from ordered
      where prev_bt is not null
        and bucket_time - prev_bt > interval '{step_interval}'
    )
    select
      '{table}'::text as table_name,
      pair,
      count(*)::int as gap_windows,
      coalesce(sum(missing_steps), 0)::int as missing_steps_total,
      coalesce(max(missing_steps), 0)::int as largest_gap_steps
    from gaps
    group by pair
    order by pair
    """


def collect_gap_summary(db_url: str, pairs: list[str], summary_start: str | None) -> dict[str, list[dict[str, object]]]:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    out: dict[str, list[dict[str, object]]] = {}
    for table, step in TF_TABLES:
        rows = psql_rows(db_url, gap_summary_sql(table, step, pair_sql, summary_start))
        parsed: list[dict[str, object]] = []
        for r in rows:
            tname, pair, gap_windows, missing_total, largest_gap = r.split("|")
            parsed.append(
                {
                    "table": tname,
                    "pair": pair,
                    "gap_windows": int(gap_windows),
                    "missing_steps_total": int(missing_total),
                    "largest_gap_steps": int(largest_gap),
                }
            )
        out[table] = parsed
    return out


def fill_missing_1m_sql(pairs: list[str], start_ts: str | None, end_ts: str | None) -> str:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    start_expr = quote_ts(start_ts)
    end_expr = quote_ts(end_ts)
    return f"""
    with pair_list as (
      select unnest(array[{pair_sql}])::text as pair
    ), bounds as (
      select
        i.pair,
        greatest(min(i.bucket_time), coalesce({start_expr}, min(i.bucket_time))) as mn,
        least(max(i.bucket_time), coalesce({end_expr}, max(i.bucket_time))) as mx
      from indicators.ohlcv_1m i
      join pair_list p on p.pair = i.pair
      group by i.pair
    ), expected as (
      select b.pair, gs as bucket_time
      from bounds b
      cross join lateral generate_series(b.mn, b.mx, interval '1 minute') gs
    ), missing as (
      select e.pair, e.bucket_time
      from expected e
      left join indicators.ohlcv_1m i
        on i.pair = e.pair
       and i.bucket_time = e.bucket_time
      where i.bucket_time is null
    ), seeded as (
      select
        m.pair,
        m.bucket_time,
        coalesce(prev.close, nxt.open) as px
      from missing m
      left join lateral (
        select i.close
        from indicators.ohlcv_1m i
        where i.pair = m.pair
          and i.bucket_time < m.bucket_time
        order by i.bucket_time desc
        limit 1
      ) prev on true
      left join lateral (
        select i.open
        from indicators.ohlcv_1m i
        where i.pair = m.pair
          and i.bucket_time > m.bucket_time
        order by i.bucket_time asc
        limit 1
      ) nxt on true
      where coalesce(prev.close, nxt.open) is not null
    )
    insert into indicators.ohlcv_1m (
      pair, bucket_time, open, high, low, close, volume, buy_volume, sell_volume, trade_count, created_at
    )
    select
      s.pair,
      s.bucket_time,
      s.px as open,
      s.px as high,
      s.px as low,
      s.px as close,
      0::numeric as volume,
      0::numeric as buy_volume,
      0::numeric as sell_volume,
      0::int as trade_count,
      now()
    from seeded s
    on conflict (pair, bucket_time) do nothing
    returning pair, bucket_time
    """


def fill_missing_1m_count_sql(pairs: list[str], start_ts: str | None, end_ts: str | None) -> str:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    start_expr = quote_ts(start_ts)
    end_expr = quote_ts(end_ts)
    return f"""
    with pair_list as (
      select unnest(array[{pair_sql}])::text as pair
    ), bounds as (
      select
        i.pair,
        greatest(min(i.bucket_time), coalesce({start_expr}, min(i.bucket_time))) as mn,
        least(max(i.bucket_time), coalesce({end_expr}, max(i.bucket_time))) as mx
      from indicators.ohlcv_1m i
      join pair_list p on p.pair = i.pair
      group by i.pair
    ), expected as (
      select b.pair, gs as bucket_time
      from bounds b
      cross join lateral generate_series(b.mn, b.mx, interval '1 minute') gs
    ), missing as (
      select e.pair, e.bucket_time
      from expected e
      left join indicators.ohlcv_1m i
        on i.pair = e.pair
       and i.bucket_time = e.bucket_time
      where i.bucket_time is null
    ), seeded as (
      select
        m.pair,
        m.bucket_time,
        coalesce(prev.close, nxt.open) as px
      from missing m
      left join lateral (
        select i.close
        from indicators.ohlcv_1m i
        where i.pair = m.pair
          and i.bucket_time < m.bucket_time
        order by i.bucket_time desc
        limit 1
      ) prev on true
      left join lateral (
        select i.open
        from indicators.ohlcv_1m i
        where i.pair = m.pair
          and i.bucket_time > m.bucket_time
        order by i.bucket_time asc
        limit 1
      ) nxt on true
      where coalesce(prev.close, nxt.open) is not null
    )
    select count(*)::int from seeded
    """


def parse_inserted_rows(rows: list[str]) -> list[tuple[str, datetime]]:
    out: list[tuple[str, datetime]] = []
    for line in rows:
        if "|" not in line:
            continue
        pair, ts = line.split("|", 1)
        out.append((pair, datetime.fromisoformat(ts.replace("Z", "+00:00"))))
    return out


def floor_bucket(ts: datetime, minutes: int) -> datetime:
    epoch = ts.timestamp()
    step = minutes * 60
    floored = floor(epoch / step) * step
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def rebuild_impacted_rollups(db_url: str, inserted: list[tuple[str, datetime]]) -> dict[str, int]:
    frame_minutes = [5, 10, 15, 30, 45, 60, 120, 360, 720]
    targets: set[tuple[str, str, str]] = set()
    for pair, ts in inserted:
        for mins in frame_minutes:
            tf = f"{mins}m" if mins < 60 else ("1h" if mins == 60 else ("2h" if mins == 120 else ("6h" if mins == 360 else "12h")))
            bt = floor_bucket(ts.astimezone(timezone.utc), mins).isoformat().replace("+00:00", "+00")
            targets.add((pair, tf, bt))

    if not targets:
        return {}

    targets_list = sorted(targets)
    counts: dict[str, int] = {}
    chunk_size = 500
    for i in range(0, len(targets_list), chunk_size):
        chunk = targets_list[i : i + chunk_size]
        values = ",\n".join(
            f"('{pair}'::text, '{tf}'::text, '{bt}'::timestamptz)" for pair, tf, bt in chunk
        )
        sql = f"""
        with v(pair, timeframe, bucket_time) as (
          values
          {values}
        )
        select count(*)::int
        from (
          select indicators.fn_rollup_ohlcv(v.pair, v.timeframe, v.bucket_time)
          from v
        ) x
        """
        psql_scalar(db_url, sql)
        for _, tf, _ in chunk:
            counts[tf] = counts.get(tf, 0) + 1
    return counts


def rebuild_missing_rollup_gaps(db_url: str, pairs: list[str], start_ts: str | None, end_ts: str | None) -> dict[str, int]:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    start_bound = f"and bucket_time >= {quote_ts(start_ts)}" if start_ts else ""
    end_bound = f"and bucket_time <= {quote_ts(end_ts)}" if end_ts else ""
    frames = [
        ("5m", "ohlcv_5m", "5 minutes"),
        ("10m", "ohlcv_10m", "10 minutes"),
        ("15m", "ohlcv_15m", "15 minutes"),
        ("30m", "ohlcv_30m", "30 minutes"),
        ("45m", "ohlcv_45m", "45 minutes"),
        ("1h", "ohlcv_1h", "1 hour"),
        ("2h", "ohlcv_2h", "2 hours"),
        ("6h", "ohlcv_6h", "6 hours"),
        ("12h", "ohlcv_12h", "12 hours"),
    ]
    out: dict[str, int] = {}
    for tf, table, step in frames:
        sql = f"""
        with bounds as (
          select pair, min(bucket_time) as mn, max(bucket_time) as mx
          from indicators.ohlcv_1m
          where pair in ({pair_sql})
            {start_bound}
            {end_bound}
          group by pair
        ), expected as (
          select b.pair,
                 generate_series(
                    date_bin(interval '{step}', b.mn, timestamptz '2000-01-01 00:00:00+00'),
                    date_bin(interval '{step}', b.mx, timestamptz '2000-01-01 00:00:00+00'),
                    interval '{step}'
                 ) as bucket_time
          from bounds b
        ), missing as (
          select e.pair, e.bucket_time
          from expected e
          left join indicators.{table} t
            on t.pair = e.pair
           and t.bucket_time = e.bucket_time
          where t.bucket_time is null
        )
        select count(*)::int
        from (
          select indicators.fn_rollup_ohlcv(m.pair, '{tf}', m.bucket_time)
          from missing m
        ) x
        """
        out[tf] = int(psql_scalar(db_url, sql) or "0")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Repair missing OHLCV buckets in indicators schema")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD")
    ap.add_argument("--start", default=None, help="Optional inclusive UTC start bound for fill window")
    ap.add_argument("--end", default=None, help="Optional inclusive UTC end bound for fill window")
    ap.add_argument(
        "--summary-start",
        default="2026-01-22 08:00:00+00",
        help="Gap-summary start bound (set empty string for unbounded)",
    )
    ap.add_argument("--rebuild-rollups", action="store_true", help="Safely rebuild impacted higher-timeframe buckets")
    ap.add_argument(
        "--repair-rollup-gaps",
        action="store_true",
        help="Repair all missing higher-timeframe buckets using 1m-derived expected grid",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]

    summary_start = args.summary_start if args.summary_start else None

    fill_start = args.start if args.start is not None else summary_start
    fill_end = args.end

    report: dict[str, object] = {
        "ran_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "pairs": pairs,
        "start": fill_start,
        "end": fill_end,
        "summary_start": summary_start,
        "before": collect_gap_summary(db_url, pairs, summary_start),
        "inserted_count": 0,
        "inserted_sample": [],
        "rollup_rebuild": None,
        "rollup_gap_repair": None,
        "after": None,
    }

    fill_sql = fill_missing_1m_sql(pairs, fill_start, fill_end)
    if not args.dry_run:
        inserted_rows = psql_rows(db_url, fill_sql)
        inserted_parsed = parse_inserted_rows(inserted_rows)
        report["inserted_count"] = len(inserted_parsed)
        report["inserted_sample"] = [
            f"{pair}|{ts.isoformat().replace('+00:00', '+00')}" for pair, ts in inserted_parsed[:20]
        ]

        if args.rebuild_rollups:
            rollup_counts = rebuild_impacted_rollups(db_url, inserted_parsed)
            report["rollup_rebuild"] = {"mode": "non_destructive_impacted_buckets", "counts_by_timeframe": rollup_counts}
        if args.repair_rollup_gaps:
            report["rollup_gap_repair"] = {
                "mode": "non_destructive_missing_grid",
                "counts_by_timeframe": rebuild_missing_rollup_gaps(db_url, pairs, fill_start, fill_end),
            }
    else:
        dry_rows = psql_rows(db_url, fill_missing_1m_count_sql(pairs, fill_start, fill_end))
        report["would_insert_count"] = int(dry_rows[0]) if dry_rows else 0

    report["after"] = collect_gap_summary(db_url, pairs, summary_start)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
