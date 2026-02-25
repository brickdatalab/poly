#!/usr/bin/env python3
"""
Audit OHLCV sequential completeness for a rolling N-day UTC window.

Checks per timeframe/pair:
1) expected bucket count vs actual distinct bucket count
2) missing buckets (anti-join against generate_series)
3) duplicate rows (same pair + bucket_time)
4) misaligned buckets (bucket_time modulo timeframe step)
5) gap violations (lag(bucket_time) continuity breaks)

Usage:
  python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Final


TIMEFRAME_SPECS: Final[tuple[tuple[str, int], ...]] = (
    ("1m", 60),
    ("5m", 300),
    ("10m", 600),
    ("15m", 900),
    ("30m", 1800),
    ("45m", 2700),
    ("1h", 3600),
    ("2h", 7200),
    ("6h", 21600),
    ("12h", 43200),
)

DEFAULT_PAIRS: Final[tuple[str, ...]] = ("BTC-USD", "ETH-USD", "SOL-USD")
PAIR_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]+$")


@dataclasses.dataclass(frozen=True)
class PairTimeframeResult:
    timeframe: str
    step_seconds: int
    pair: str
    expected_rows: int
    actual_distinct_rows: int
    missing_rows: int
    duplicate_rows: int
    misaligned_rows: int
    gap_violations: int
    first_missing: str | None
    last_missing: str | None
    status: str


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def psql_json(db_url: str, db_password: str | None, sql: str, timeout_s: int = 90) -> Any:
    env = os.environ.copy()
    if db_password:
        env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")
    cmd = ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", sql]
    try:
        out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"psql timed out after {timeout_s}s") from exc
    except subprocess.CalledProcessError as exc:
        msg = exc.output.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"psql failed: {msg}") from exc

    text = out.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    return json.loads(text)


def parse_pairs(pairs_csv: str) -> tuple[str, ...]:
    parsed = tuple(p.strip() for p in pairs_csv.split(",") if p.strip())
    if not parsed:
        raise ValueError("No pairs provided")
    bad = [p for p in parsed if not PAIR_PATTERN.match(p)]
    if bad:
        raise ValueError(f"Invalid pair value(s): {bad}")
    return parsed


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_timeframe_sql(*, schema: str, timeframe: str, step_seconds: int, pairs: tuple[str, ...], days: int) -> str:
    table = f"{schema}.ohlcv_{timeframe}"
    pair_literals = ", ".join(quote_literal(p) for p in pairs)
    return f"""
    with bounds as (
      select
        (date_trunc('minute', now() at time zone 'UTC') - interval '{days} days')::timestamptz as start_ts,
        date_trunc('minute', now() at time zone 'UTC')::timestamptz as end_ts
    ),
    range_bounds as (
      select
        to_timestamp(floor(extract(epoch from start_ts) / {step_seconds}) * {step_seconds})::timestamptz as start_aligned,
        to_timestamp(floor(extract(epoch from end_ts) / {step_seconds}) * {step_seconds})::timestamptz as end_aligned
      from bounds
    ),
    pairs as (
      select unnest(array[{pair_literals}]::text[]) as pair
    ),
    expected as (
      select
        p.pair,
        gs::timestamptz as bucket_time
      from pairs p
      cross join range_bounds rb
      cross join generate_series(
        rb.start_aligned,
        rb.end_aligned - interval '1 second' * {step_seconds},
        interval '1 second' * {step_seconds}
      ) gs
    ),
    actual_raw as (
      select
        pair,
        bucket_time,
        to_timestamp(floor(extract(epoch from bucket_time) / {step_seconds}) * {step_seconds})::timestamptz as bucket_aligned
      from {table}, range_bounds
      where pair = any(array[{pair_literals}]::text[])
        and bucket_time >= range_bounds.start_aligned - interval '1 second' * {step_seconds}
        and bucket_time < range_bounds.end_aligned + interval '1 second' * {step_seconds}
    ),
    actual_bucketed as (
      select
        pair,
        bucket_time,
        bucket_aligned
      from actual_raw, range_bounds
      where bucket_aligned >= range_bounds.start_aligned
        and bucket_aligned < range_bounds.end_aligned
    ),
    actual_distinct as (
      select distinct pair, bucket_aligned as bucket_time
      from actual_bucketed
    ),
    expected_counts as (
      select pair, count(*)::bigint as expected_rows
      from expected
      group by pair
    ),
    actual_counts as (
      select pair, count(*)::bigint as actual_distinct_rows
      from actual_distinct
      group by pair
    ),
    missing as (
      select e.pair, e.bucket_time
      from expected e
      left join actual_distinct a
        on a.pair = e.pair
       and a.bucket_time = e.bucket_time
      where a.bucket_time is null
    ),
    missing_stats as (
      select
        pair,
        count(*)::bigint as missing_rows,
        min(bucket_time) as first_missing,
        max(bucket_time) as last_missing
      from missing
      group by pair
    ),
    duplicate_stats as (
      select
        pair,
        greatest(count(*) - count(distinct bucket_aligned), 0)::bigint as duplicate_rows
      from actual_bucketed
      group by pair
    ),
    misaligned_stats as (
      select
        pair,
        sum(
          case
            when bucket_time = bucket_aligned then 0
            else 1
          end
        )::bigint as misaligned_rows
      from actual_bucketed
      group by pair
    ),
    gap_stats as (
      select
        pair,
        sum(
          case
            when prev_bucket_time is null then 0
            when bucket_time - prev_bucket_time = interval '1 second' * {step_seconds} then 0
            else 1
          end
        )::bigint as gap_violations
      from (
        select
          pair,
          bucket_time,
          lag(bucket_time) over (partition by pair order by bucket_time) as prev_bucket_time
        from actual_distinct
      ) s
      group by pair
    )
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select
        '{timeframe}'::text as timeframe,
        {step_seconds}::int as step_seconds,
        p.pair,
        coalesce(ec.expected_rows, 0)::bigint as expected_rows,
        coalesce(ac.actual_distinct_rows, 0)::bigint as actual_distinct_rows,
        coalesce(ms.missing_rows, 0)::bigint as missing_rows,
        coalesce(ds.duplicate_rows, 0)::bigint as duplicate_rows,
        coalesce(als.misaligned_rows, 0)::bigint as misaligned_rows,
        coalesce(gs.gap_violations, 0)::bigint as gap_violations,
        ms.first_missing,
        ms.last_missing
      from pairs p
      left join expected_counts ec using (pair)
      left join actual_counts ac using (pair)
      left join missing_stats ms using (pair)
      left join duplicate_stats ds using (pair)
      left join misaligned_stats als using (pair)
      left join gap_stats gs using (pair)
      order by p.pair
    ) t;
    """


def to_status(row: dict[str, Any]) -> str:
    expected = int(row.get("expected_rows") or 0)
    actual = int(row.get("actual_distinct_rows") or 0)
    missing = int(row.get("missing_rows") or 0)
    dup = int(row.get("duplicate_rows") or 0)
    misaligned = int(row.get("misaligned_rows") or 0)
    gaps = int(row.get("gap_violations") or 0)
    ok = (
        expected > 0
        and expected == actual
        and missing == 0
        and dup == 0
        and misaligned == 0
        and gaps == 0
    )
    return "PASS" if ok else "FAIL"


def run_audit(db_url: str, db_password: str | None, schema: str, pairs: tuple[str, ...], days: int) -> dict[str, list[PairTimeframeResult]]:
    by_timeframe: dict[str, list[PairTimeframeResult]] = {}
    for timeframe, step in TIMEFRAME_SPECS:
        sql = build_timeframe_sql(schema=schema, timeframe=timeframe, step_seconds=step, pairs=pairs, days=days)
        rows = psql_json(db_url, db_password, sql, timeout_s=120) or []
        parsed: list[PairTimeframeResult] = []
        for row in rows:
            parsed.append(
                PairTimeframeResult(
                    timeframe=str(row["timeframe"]),
                    step_seconds=int(row["step_seconds"]),
                    pair=str(row["pair"]),
                    expected_rows=int(row["expected_rows"]),
                    actual_distinct_rows=int(row["actual_distinct_rows"]),
                    missing_rows=int(row["missing_rows"]),
                    duplicate_rows=int(row["duplicate_rows"]),
                    misaligned_rows=int(row["misaligned_rows"]),
                    gap_violations=int(row["gap_violations"]),
                    first_missing=row.get("first_missing"),
                    last_missing=row.get("last_missing"),
                    status=to_status(row),
                )
            )
        by_timeframe[timeframe] = parsed
    return by_timeframe


def summarize(by_timeframe: dict[str, list[PairTimeframeResult]]) -> tuple[int, int]:
    total = 0
    failed = 0
    for rows in by_timeframe.values():
        for row in rows:
            total += 1
            if row.status != "PASS":
                failed += 1
    return total, failed


def print_report(by_timeframe: dict[str, list[PairTimeframeResult]], tldr: bool) -> None:
    if tldr:
        for timeframe, rows in by_timeframe.items():
            failures = [r for r in rows if r.status != "PASS"]
            if not failures:
                continue
            print(f"\n[{timeframe}] failures")
            for r in failures:
                print(
                    f"- {r.pair}: expected={r.expected_rows} actual={r.actual_distinct_rows} "
                    f"missing={r.missing_rows} gaps={r.gap_violations} dup={r.duplicate_rows} "
                    f"misaligned={r.misaligned_rows} first_missing={r.first_missing} last_missing={r.last_missing}"
                )
        return

    for timeframe, rows in by_timeframe.items():
        print(f"\n[{timeframe}]")
        for r in rows:
            print(
                f"{r.status:4} {r.pair:8} expected={r.expected_rows:5d} actual={r.actual_distinct_rows:5d} "
                f"missing={r.missing_rows:3d} gaps={r.gap_violations:3d} dup={r.duplicate_rows:3d} misaligned={r.misaligned_rows:3d}"
            )


def build_output_payload(*, schema: str, pairs: tuple[str, ...], days: int, by_timeframe: dict[str, list[PairTimeframeResult]]) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    total, failed = summarize(by_timeframe)
    return {
        "generated_at_utc": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "window_days": days,
        "schema": schema,
        "pairs": list(pairs),
        "summary": {"total_checks": total, "failed_checks": failed, "all_pass": failed == 0},
        "timeframes": {
            tf: [dataclasses.asdict(row) for row in rows]
            for tf, rows in by_timeframe.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit OHLCV sequential completeness over the last N UTC days")
    parser.add_argument("--days", type=int, default=5, help="rolling lookback in UTC days (default: 5)")
    parser.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD", help="comma-separated pair list")
    parser.add_argument("--schema", default="indicators", help="schema containing ohlcv_* tables (default: indicators)")
    parser.add_argument("--tldr", action="store_true", help="print only failing rows")
    args = parser.parse_args()

    if args.days <= 0:
        raise SystemExit("--days must be > 0")

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    db_url = require_env("SUPABASE_DB_URL")
    db_password = os.environ.get("SUPABASE_DB_PASSWORD")
    pairs = parse_pairs(args.pairs)

    by_timeframe = run_audit(db_url=db_url, db_password=db_password, schema=args.schema, pairs=pairs, days=args.days)
    print_report(by_timeframe, tldr=args.tldr)

    payload = build_output_payload(schema=args.schema, pairs=pairs, days=args.days, by_timeframe=by_timeframe)
    out_dir = repo_root / "utility-scripts" / "ohlcv" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"ohlcv_sequential_audit_{args.days}d_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    total, failed = summarize(by_timeframe)
    print(f"\nSummary: {total - failed}/{total} checks passed.")
    print(f"Report JSON: {out_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
