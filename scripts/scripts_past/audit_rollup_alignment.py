from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alpha_v4.db import fetch_all, get_connection
from alpha_v4.time_utils import parse_iso_utc

DEFAULT_PAIRS = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclass(frozen=True)
class TimeframeSpec:
    timeframe: str
    table_name: str
    step_minutes: int


TIMEFRAME_SPECS: dict[str, TimeframeSpec] = {
    "5m": TimeframeSpec("5m", "indicators.ohlcv_5m", 5),
    "10m": TimeframeSpec("10m", "indicators.ohlcv_10m", 10),
    "15m": TimeframeSpec("15m", "indicators.ohlcv_15m", 15),
    "30m": TimeframeSpec("30m", "indicators.ohlcv_30m", 30),
    "45m": TimeframeSpec("45m", "indicators.ohlcv_45m", 45),
    "1h": TimeframeSpec("1h", "indicators.ohlcv_1h", 60),
    "2h": TimeframeSpec("2h", "indicators.ohlcv_2h", 120),
    "6h": TimeframeSpec("6h", "indicators.ohlcv_6h", 360),
    "12h": TimeframeSpec("12h", "indicators.ohlcv_12h", 720),
}
DEFAULT_TIMEFRAMES = tuple(TIMEFRAME_SPECS.keys())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit for misaligned bucket_time rows in rollup OHLCV tables."
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
    parser.add_argument("--start", default=None, help="Optional inclusive ISO-8601 UTC lower bound.")
    parser.add_argument("--end", default=None, help="Optional inclusive ISO-8601 UTC upper bound.")
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=5,
        help="Sample count of misaligned bucket times per pair/timeframe.",
    )
    parser.add_argument(
        "--report-out",
        default=None,
        help="Output JSON path. Default: exports/rollup_alignment_audit_<utc>.json",
    )
    return parser.parse_args(argv)


def default_report_path(now_utc: datetime) -> str:
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    return f"exports/rollup_alignment_audit_{stamp}.json"


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
    pairs = [pair.upper() for pair in parse_csv_values(raw)]
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


def parse_optional_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return parse_iso_utc(value).replace(second=0, microsecond=0)


def build_alignment_sql(table_name: str, *, include_start: bool, include_end: bool) -> str:
    where_clauses = ["pair = ANY(%s)"]
    if include_start:
        where_clauses.append("bucket_time >= %s::timestamptz")
    if include_end:
        where_clauses.append("bucket_time <= %s::timestamptz")
    where_sql = " AND ".join(where_clauses)
    return f"""
        SELECT
            pair,
            COUNT(*)::int AS total_rows,
            SUM(CASE WHEN MOD(EXTRACT(EPOCH FROM bucket_time)::bigint, %s) = 0 THEN 1 ELSE 0 END)::int AS aligned_rows,
            SUM(CASE WHEN MOD(EXTRACT(EPOCH FROM bucket_time)::bigint, %s) <> 0 THEN 1 ELSE 0 END)::int AS misaligned_rows
        FROM {table_name}
        WHERE {where_sql}
        GROUP BY pair
        ORDER BY pair
    """


def build_samples_sql(table_name: str, *, include_start: bool, include_end: bool) -> str:
    where_clauses = [
        "pair = %s",
        "MOD(EXTRACT(EPOCH FROM bucket_time)::bigint, %s) <> 0",
    ]
    if include_start:
        where_clauses.append("bucket_time >= %s::timestamptz")
    if include_end:
        where_clauses.append("bucket_time <= %s::timestamptz")
    where_sql = " AND ".join(where_clauses)
    return f"""
        SELECT bucket_time
        FROM {table_name}
        WHERE {where_sql}
        ORDER BY bucket_time ASC
        LIMIT %s
    """


def make_result_row(
    *,
    timeframe: str,
    table_name: str,
    pair: str,
    step_minutes: int,
    total_rows: int,
    aligned_rows: int,
    misaligned_rows: int,
    samples: list[datetime],
) -> dict[str, Any]:
    misaligned_pct = round((misaligned_rows / total_rows) * 100.0, 4) if total_rows else 0.0
    return {
        "timeframe": timeframe,
        "table_name": table_name,
        "pair": pair,
        "step_minutes": step_minutes,
        "total_rows": total_rows,
        "aligned_rows": aligned_rows,
        "misaligned_rows": misaligned_rows,
        "misaligned_pct": misaligned_pct,
        "flagged": misaligned_rows > 0,
        "sample_misaligned_buckets": [sample.astimezone(timezone.utc).isoformat() for sample in samples],
    }


def build_alignment_params(
    *,
    step_seconds: int,
    pairs: list[str],
    start: datetime | None,
    end: datetime | None,
) -> tuple[Any, ...]:
    params: list[Any] = [step_seconds, step_seconds, pairs]
    if start is not None:
        params.append(start)
    if end is not None:
        params.append(end)
    return tuple(params)


def build_sample_params(
    *,
    pair: str,
    step_seconds: int,
    start: datetime | None,
    end: datetime | None,
    sample_limit: int,
) -> tuple[Any, ...]:
    params: list[Any] = [pair, step_seconds]
    if start is not None:
        params.append(start)
    if end is not None:
        params.append(end)
    params.append(sample_limit)
    return tuple(params)


def run_audit(
    connection,
    *,
    pairs: list[str],
    timeframes: list[str],
    start: datetime | None,
    end: datetime | None,
    sample_limit: int,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for timeframe in timeframes:
        spec = TIMEFRAME_SPECS[timeframe]
        step_seconds = spec.step_minutes * 60
        rows = fetch_all(
            connection,
            build_alignment_sql(
                spec.table_name,
                include_start=start is not None,
                include_end=end is not None,
            ),
            build_alignment_params(
                step_seconds=step_seconds,
                pairs=pairs,
                start=start,
                end=end,
            ),
        )
        rows_by_pair = {row["pair"]: row for row in rows}
        for pair in pairs:
            pair_row = rows_by_pair.get(
                pair,
                {
                    "total_rows": 0,
                    "aligned_rows": 0,
                    "misaligned_rows": 0,
                },
            )
            misaligned_rows = int(pair_row["misaligned_rows"])
            samples: list[datetime] = []
            if misaligned_rows > 0:
                sample_rows = fetch_all(
                    connection,
                    build_samples_sql(
                        spec.table_name,
                        include_start=start is not None,
                        include_end=end is not None,
                    ),
                    build_sample_params(
                        pair=pair,
                        step_seconds=step_seconds,
                        start=start,
                        end=end,
                        sample_limit=sample_limit,
                    ),
                )
                samples = [row["bucket_time"] for row in sample_rows]
            results.append(
                make_result_row(
                    timeframe=timeframe,
                    table_name=spec.table_name,
                    pair=pair,
                    step_minutes=spec.step_minutes,
                    total_rows=int(pair_row["total_rows"]),
                    aligned_rows=int(pair_row["aligned_rows"]),
                    misaligned_rows=misaligned_rows,
                    samples=samples,
                )
            )

    total_rows = sum(row["total_rows"] for row in results)
    total_misaligned = sum(row["misaligned_rows"] for row in results)
    flagged_pairs = sum(1 for row in results if row["flagged"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "window_start": start.isoformat() if start else None,
        "window_end": end.isoformat() if end else None,
        "summary": {
            "pairs_count": len(pairs),
            "timeframes_count": len(timeframes),
            "rows_scanned": total_rows,
            "misaligned_rows": total_misaligned,
            "flagged_pair_timeframes": flagged_pairs,
            "status": "WARN" if total_misaligned > 0 else "PASS",
        },
        "results": results,
    }


def write_report(report: dict[str, Any], output_path: str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pairs = parse_pairs(args.pairs)
    timeframes = parse_timeframes(args.timeframes)
    start = parse_optional_iso(args.start)
    end = parse_optional_iso(args.end)
    sample_limit = max(args.sample_limit, 1)
    now_utc = datetime.now(timezone.utc)
    report_out = args.report_out or default_report_path(now_utc)

    connection = get_connection(autocommit=False)
    try:
        report = run_audit(
            connection,
            pairs=pairs,
            timeframes=timeframes,
            start=start,
            end=end,
            sample_limit=sample_limit,
        )
        connection.rollback()
        write_report(report, report_out)
        print(json.dumps(report, indent=2, sort_keys=True))
        print(f"Report written to {report_out}")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Audit failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
