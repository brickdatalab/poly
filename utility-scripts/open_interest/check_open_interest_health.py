#!/usr/bin/env python3
"""
Audit open_interest freshness + bucket continuity for a rolling UTC window.
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
    build_open_interest_health_sql,
    build_output_payload,
    load_dotenv,
    parse_pairs,
    print_rows,
    psql_json,
    require_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit open_interest freshness + continuity")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="comma-separated pair list")
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=72,
        help="rolling lookback window in hours (default: 72)",
    )
    parser.add_argument(
        "--step-seconds",
        type=int,
        default=900,
        help="expected open_interest bucket step in seconds (default: 900)",
    )
    parser.add_argument("--tldr", action="store_true", help="print only non-pass rows")
    args = parser.parse_args()

    if args.lookback_hours <= 0:
        raise SystemExit("--lookback-hours must be > 0")
    if args.step_seconds <= 0:
        raise SystemExit("--step-seconds must be > 0")

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    db_url = require_env("SUPABASE_DB_URL")
    db_password = os.environ.get("SUPABASE_DB_PASSWORD")
    pairs = parse_pairs(args.pairs)

    sql = build_open_interest_health_sql(
        source="open_interest",
        table="indicators.open_interest",
        ts_column="bucket_time",
        pairs=pairs,
        lookback_hours=args.lookback_hours,
        step_seconds=args.step_seconds,
        fallback_max_lag_seconds=1200,
    )
    rows = psql_json(db_url, db_password, sql, timeout_s=120) or []

    print_rows(
        rows,
        source_label="open_interest",
        tldr=args.tldr,
        key_fields=(
            "lag_seconds",
            "max_lag_seconds",
            "expected_rows",
            "actual_distinct_rows",
            "missing_buckets",
            "gap_violations",
            "duplicate_rows",
            "misaligned_rows",
        ),
    )

    payload = build_output_payload(
        source="open_interest",
        pairs=pairs,
        window={"type": "hours", "value": args.lookback_hours, "step_seconds": args.step_seconds},
        rows=rows,
        meta={"table": "indicators.open_interest", "timestamp_column": "bucket_time"},
    )
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"open_interest_health_{args.lookback_hours}h_{stamp}.json"
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
