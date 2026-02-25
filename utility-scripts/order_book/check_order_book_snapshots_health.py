#!/usr/bin/env python3
"""
Audit order_book_snapshots source freshness and minute continuity for a rolling UTC window.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

_UTILS_ROOT = Path(__file__).resolve().parents[1]
if str(_UTILS_ROOT) not in sys.path:
    sys.path.insert(0, str(_UTILS_ROOT))

from source_health.common import (  # noqa: E402
    DEFAULT_PAIRS,
    build_output_payload,
    build_realtime_source_health_sql,
    load_dotenv,
    parse_pairs,
    print_rows,
    psql_json,
    require_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit order_book_snapshots freshness + continuity")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="comma-separated pair list")
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=180,
        help="rolling lookback window in minutes (default: 180)",
    )
    parser.add_argument("--tldr", action="store_true", help="print only non-pass rows")
    args = parser.parse_args()

    if args.lookback_minutes <= 0:
        raise SystemExit("--lookback-minutes must be > 0")

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    db_url = require_env("SUPABASE_DB_URL")
    db_password = os.environ.get("SUPABASE_DB_PASSWORD")
    pairs = parse_pairs(args.pairs)

    sql = build_realtime_source_health_sql(
        source="order_book_snapshots",
        table="public.order_book_snapshots",
        ts_column="captured_at",
        pairs=pairs,
        lookback_minutes=args.lookback_minutes,
        fallback_max_lag_seconds=120,
    )
    rows = psql_json(db_url, db_password, sql, timeout_s=120) or []

    print_rows(
        rows,
        source_label="order_book_snapshots",
        tldr=args.tldr,
        key_fields=("lag_seconds", "max_lag_seconds", "rows_last_5m", "rows_per_minute", "missing_minutes"),
    )

    payload = build_output_payload(
        source="order_book_snapshots",
        pairs=pairs,
        window={"type": "minutes", "value": args.lookback_minutes},
        rows=rows,
        meta={"table": "public.order_book_snapshots", "timestamp_column": "captured_at"},
    )
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"order_book_snapshots_health_{args.lookback_minutes}m_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    summary = payload["summary"]
    print(
        f"\nSummary: pass={summary['passed_checks']} warn={summary['warn_checks']} "
        f"fail={summary['failed_checks']} overall={summary['overall_status']} light={summary['traffic_light']}"
    )
    print(f"Report JSON: {out_path}")
    return 0 if int(summary["failed_checks"]) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

