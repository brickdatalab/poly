from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from psycopg2.extras import execute_values

from alpha_v4.db import db_cursor, fetch_all, fetch_one, get_connection
from alpha_v4.time_utils import ensure_utc, parse_iso_utc

DEFAULT_PAIRS = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclass(frozen=True)
class TimeframeSpec:
    timeframe: str
    table_name: str
    step_minutes: int
    support_minutes: int


TIMEFRAME_SPECS: dict[str, TimeframeSpec] = {
    "5m": TimeframeSpec("5m", "indicators.ohlcv_5m", step_minutes=5, support_minutes=5),
    "10m": TimeframeSpec("10m", "indicators.ohlcv_10m", step_minutes=10, support_minutes=10),
    "15m": TimeframeSpec("15m", "indicators.ohlcv_15m", step_minutes=15, support_minutes=15),
    "30m": TimeframeSpec("30m", "indicators.ohlcv_30m", step_minutes=30, support_minutes=30),
    "45m": TimeframeSpec("45m", "indicators.ohlcv_45m", step_minutes=45, support_minutes=45),
    "2h": TimeframeSpec("2h", "indicators.ohlcv_2h", step_minutes=120, support_minutes=120),
    "6h": TimeframeSpec("6h", "indicators.ohlcv_6h", step_minutes=360, support_minutes=360),
    "12h": TimeframeSpec("12h", "indicators.ohlcv_12h", step_minutes=720, support_minutes=720),
}
DEFAULT_TIMEFRAMES = tuple(TIMEFRAME_SPECS.keys())


def default_report_path(as_of: datetime) -> str:
    stamp = ensure_utc(as_of).strftime("%Y%m%dT%H%M%SZ")
    return f"exports/rollup_backfill_missing_only_{stamp}.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing rollup rows from indicators.ohlcv_1m without modifying existing rows."
    )
    parser.add_argument("--start", required=True, help="Inclusive window start (ISO-8601 UTC).")
    parser.add_argument(
        "--as-of",
        default=None,
        help="Reference timestamp (ISO-8601 UTC). End is derived as last closed bucket.",
    )
    parser.add_argument(
        "--pairs",
        default=",".join(DEFAULT_PAIRS),
        help=f"Comma-separated pairs. Default: {','.join(DEFAULT_PAIRS)}",
    )
    parser.add_argument(
        "--timeframes",
        default=",".join(DEFAULT_TIMEFRAMES),
        help=f"Comma-separated timeframes. Default: {','.join(DEFAULT_TIMEFRAMES)}",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read-only mode (default).")
    mode.add_argument("--apply", action="store_true", help="Write missing rows.")
    parser.add_argument(
        "--report-out",
        default=None,
        help="Output JSON report path. Default: exports/rollup_backfill_missing_only_<utc>.json",
    )
    parsed = parser.parse_args(argv)
    if not parsed.apply:
        parsed.dry_run = True
    return parsed


def parse_csv_values(raw: str) -> list[str]:
    values = [value.strip() for value in raw.split(",") if value.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def parse_pairs(raw: str) -> list[str]:
    pairs = [value.upper() for value in parse_csv_values(raw)]
    if not pairs:
        raise ValueError("At least one pair is required.")
    return pairs


def parse_timeframes(raw: str) -> list[str]:
    timeframes = parse_csv_values(raw)
    if not timeframes:
        raise ValueError("At least one timeframe is required.")
    unknown = [timeframe for timeframe in timeframes if timeframe not in TIMEFRAME_SPECS]
    if unknown:
        raise ValueError(f"Unsupported timeframe(s): {', '.join(unknown)}")
    return timeframes


def floor_to_step(moment: datetime, *, step_minutes: int) -> datetime:
    moment = ensure_utc(moment)
    minute_of_day = (moment.hour * 60) + moment.minute
    floored_minute_of_day = (minute_of_day // step_minutes) * step_minutes
    floored_hour = floored_minute_of_day // 60
    floored_minute = floored_minute_of_day % 60
    return moment.replace(hour=floored_hour, minute=floored_minute, second=0, microsecond=0)


def compute_last_closed_bucket(as_of: datetime, *, step_minutes: int) -> datetime:
    return floor_to_step(as_of, step_minutes=step_minutes) - timedelta(minutes=step_minutes)


def expected_bucket_count(start: datetime, end: datetime, *, step_minutes: int) -> int:
    if end < start:
        return 0
    span_seconds = int((end - start).total_seconds())
    return (span_seconds // (step_minutes * 60)) + 1


def build_missing_buckets_sql(table_name: str) -> str:
    return f"""
        WITH expected AS (
            SELECT generate_series(
                %s::timestamptz,
                %s::timestamptz,
                %s::interval
            ) AS bucket_time
        ),
        actual AS (
            SELECT bucket_time
            FROM {table_name}
            WHERE pair = %s
              AND bucket_time BETWEEN %s::timestamptz AND %s::timestamptz
        )
        SELECT expected.bucket_time
        FROM expected
        LEFT JOIN actual USING (bucket_time)
        WHERE actual.bucket_time IS NULL
        ORDER BY expected.bucket_time
    """


def build_eligible_rollup_sql(*, step_minutes: int) -> str:
    return f"""
        SELECT
            missing.bucket_time AS bucket_time,
            COUNT(src.bucket_time)::int AS support_count,
            (ARRAY_AGG(src.open ORDER BY src.bucket_time ASC))[1] AS open,
            MAX(src.high) AS high,
            MIN(src.low) AS low,
            (ARRAY_AGG(src.close ORDER BY src.bucket_time DESC))[1] AS close,
            COALESCE(SUM(src.volume), 0) AS volume,
            COALESCE(SUM(src.buy_volume), 0) AS buy_volume,
            COALESCE(SUM(src.sell_volume), 0) AS sell_volume,
            SUM(src.trade_count)::int AS trade_count
        FROM (
            SELECT UNNEST(%s::timestamptz[]) AS bucket_time
        ) AS missing
        LEFT JOIN indicators.ohlcv_1m AS src
          ON src.pair = %s
         AND src.bucket_time >= missing.bucket_time
         AND src.bucket_time < missing.bucket_time + interval '{step_minutes} minutes'
        GROUP BY missing.bucket_time
        ORDER BY missing.bucket_time
    """


def build_insert_sql(table_name: str) -> str:
    return f"""
        INSERT INTO {table_name} (
            pair,
            bucket_time,
            open,
            high,
            low,
            close,
            volume,
            buy_volume,
            sell_volume,
            trade_count,
            created_at
        )
        VALUES %s
        ON CONFLICT (pair, bucket_time) DO NOTHING
        RETURNING bucket_time
    """


def fetch_present_count(
    connection,
    *,
    table_name: str,
    pair: str,
    start: datetime,
    end: datetime,
) -> int:
    row = fetch_one(
        connection,
        f"""
        SELECT COUNT(*)::int AS count
        FROM {table_name}
        WHERE pair = %s
          AND bucket_time BETWEEN %s::timestamptz AND %s::timestamptz
        """,
        (pair, start, end),
    )
    return int(row["count"]) if row else 0


def fetch_missing_buckets(
    connection,
    *,
    table_name: str,
    pair: str,
    start: datetime,
    end: datetime,
    step_minutes: int,
) -> list[datetime]:
    rows = fetch_all(
        connection,
        build_missing_buckets_sql(table_name),
        (
            start,
            end,
            f"{step_minutes} minutes",
            pair,
            start,
            end,
        ),
    )
    return [ensure_utc(row["bucket_time"]) for row in rows]


def fetch_eligible_rollups(
    connection,
    *,
    pair: str,
    missing_buckets: list[datetime],
    step_minutes: int,
) -> list[dict[str, Any]]:
    if not missing_buckets:
        return []
    rows = fetch_all(
        connection,
        build_eligible_rollup_sql(step_minutes=step_minutes),
        (missing_buckets, pair),
    )
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if int(row["support_count"]) != step_minutes:
            continue
        eligible.append(
            {
                "bucket_time": ensure_utc(row["bucket_time"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "buy_volume": row["buy_volume"],
                "sell_volume": row["sell_volume"],
                "trade_count": int(row["trade_count"]),
            }
        )
    return eligible


def insert_rollups(
    connection,
    *,
    table_name: str,
    pair: str,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    now_utc = datetime.now(timezone.utc)
    values = [
        (
            pair,
            row["bucket_time"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
            row["buy_volume"],
            row["sell_volume"],
            row["trade_count"],
            now_utc,
        )
        for row in rows
    ]
    with db_cursor(connection) as cursor:
        inserted = execute_values(
            cursor,
            build_insert_sql(table_name),
            values,
            page_size=500,
            fetch=True,
        )
    return len(inserted)


def run_backfill(
    connection,
    *,
    start: datetime,
    as_of: datetime,
    pairs: list[str],
    timeframes: list[str],
    apply: bool,
) -> dict[str, Any]:
    utc_start = ensure_utc(start).replace(second=0, microsecond=0)
    utc_as_of = ensure_utc(as_of).replace(second=0, microsecond=0)
    results: list[dict[str, Any]] = []
    for timeframe in timeframes:
        spec = TIMEFRAME_SPECS[timeframe]
        window_end = compute_last_closed_bucket(utc_as_of, step_minutes=spec.step_minutes)
        for pair in pairs:
            if window_end < utc_start:
                results.append(
                    {
                        "pair": pair,
                        "timeframe": timeframe,
                        "table_name": spec.table_name,
                        "start": utc_start.isoformat(),
                        "end": window_end.isoformat(),
                        "expected": 0,
                        "present": 0,
                        "missing": 0,
                        "eligible": 0,
                        "inserted": 0,
                        "skipped": 0,
                    }
                )
                continue

            expected = expected_bucket_count(utc_start, window_end, step_minutes=spec.step_minutes)
            present = fetch_present_count(
                connection,
                table_name=spec.table_name,
                pair=pair,
                start=utc_start,
                end=window_end,
            )
            missing_buckets = fetch_missing_buckets(
                connection,
                table_name=spec.table_name,
                pair=pair,
                start=utc_start,
                end=window_end,
                step_minutes=spec.step_minutes,
            )
            eligible_rows = fetch_eligible_rollups(
                connection,
                pair=pair,
                missing_buckets=missing_buckets,
                step_minutes=spec.support_minutes,
            )
            inserted = (
                insert_rollups(connection, table_name=spec.table_name, pair=pair, rows=eligible_rows)
                if apply
                else 0
            )
            results.append(
                {
                    "pair": pair,
                    "timeframe": timeframe,
                    "table_name": spec.table_name,
                    "start": utc_start.isoformat(),
                    "end": window_end.isoformat(),
                    "expected": expected,
                    "present": present,
                    "missing": len(missing_buckets),
                    "eligible": len(eligible_rows),
                    "inserted": inserted,
                    "skipped": max(len(missing_buckets) - len(eligible_rows), 0),
                }
            )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": utc_as_of.isoformat(),
        "start": utc_start.isoformat(),
        "apply": apply,
        "results": results,
    }


def write_report(report: dict[str, Any], output_path: str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start = parse_iso_utc(args.start)
    as_of = parse_iso_utc(args.as_of) if args.as_of else datetime.now(timezone.utc)
    pairs = parse_pairs(args.pairs)
    timeframes = parse_timeframes(args.timeframes)
    apply = bool(args.apply)
    report_out = args.report_out or default_report_path(as_of)

    connection = get_connection(autocommit=False)
    try:
        report = run_backfill(
            connection,
            start=start,
            as_of=as_of,
            pairs=pairs,
            timeframes=timeframes,
            apply=apply,
        )
        if apply:
            connection.commit()
        else:
            connection.rollback()
        write_report(report, report_out)
        print(json.dumps(report, indent=2, sort_keys=True))
        print(f"Report written to {report_out}")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Backfill failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
