#!/usr/bin/env python3
"""Run indicator compute latency snapshot and emit AI-friendly JSON output."""

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
    load_dotenv,
    parse_pairs,
    psql_json,
    require_env,
)


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ops.fn_indicator_compute_latency_snapshot")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="comma-separated pair list")
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=24,
        help="lookback window in hours (default: 24)",
    )
    parser.add_argument("--tldr", action="store_true", help="print only non-pass rows")
    args = parser.parse_args()

    if args.lookback_hours <= 0:
        raise SystemExit("--lookback-hours must be > 0")

    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    db_url = require_env("SUPABASE_DB_URL")
    db_password = os.environ.get("SUPABASE_DB_PASSWORD")
    pairs = parse_pairs(args.pairs)

    pair_literals = ", ".join(quote_literal(p) for p in pairs)
    sql = f"""
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select ops.fn_indicator_compute_latency_snapshot(
        array[{pair_literals}]::text[],
        interval '{int(args.lookback_hours)} hours'
      ) as report
    ) t;
    """
    rows = psql_json(db_url, db_password, sql, timeout_s=120) or []
    report = rows[0]["report"] if rows else {"summary": {}, "rows": []}

    summary = report.get("summary", {})
    out_rows = report.get("rows", [])

    if args.tldr:
        non_pass = [r for r in out_rows if str(r.get("status", "")).upper() != "PASS"]
        if not non_pass:
            print("[indicator_latency] no failures/warnings")
        else:
            print("[indicator_latency] non-pass rows")
            for row in non_pass:
                print(
                    f"- pair={row.get('pair')} timeframe={row.get('timeframe')} config_id={row.get('config_id')} "
                    f"status={row.get('status')} reason={row.get('reason_code')} "
                    f"p95_latency_seconds={row.get('p95_latency_seconds')} p99_latency_seconds={row.get('p99_latency_seconds')}"
                )
    else:
        for row in out_rows:
            print(
                f"{row.get('status'):4} pair={row.get('pair')} timeframe={row.get('timeframe')} "
                f"config_id={row.get('config_id')} p95_latency_seconds={row.get('p95_latency_seconds')} "
                f"p99_latency_seconds={row.get('p99_latency_seconds')} reason={row.get('reason_code')}"
            )

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "indicator_compute_latency",
        "pairs": list(pairs),
        "window": {"type": "hours", "value": args.lookback_hours},
        "summary": summary,
        "rows": out_rows,
    }
    out_path = Path(__file__).resolve().parent / "output" / f"indicator_compute_latency_{args.lookback_hours}h_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(
        f"\nSummary: pass={summary.get('passed_checks', 0)} warn={summary.get('warn_checks', 0)} "
        f"fail={summary.get('failed_checks', 0)} overall={summary.get('overall_status', 'UNKNOWN')} "
        f"light={summary.get('traffic_light', 'UNKNOWN')}"
    )
    print(f"Report JSON: {out_path}")

    return 0 if int(summary.get("failed_checks", 0)) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
