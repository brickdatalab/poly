#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine import evaluate_indicator, list_indicators, parse_pairs, table


def _run_one(indicator: str, pairs: list[str], bucket_time: str | None) -> dict[str, Any]:
    return evaluate_indicator(indicator, pairs, bucket_time)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run all standalone synthetic signal producers.")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD", help="Comma-separated pairs")
    ap.add_argument("--bucket-time", default=None, help="Optional UTC bucket_time override")
    ap.add_argument("--workers", type=int, default=2, help="Parallel worker count (default: 2)")
    ap.add_argument("--pretty", action="store_true", help="Pretty print summary tables")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero if any missing input is found")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    pairs = parse_pairs(args.pairs)
    indicators = list_indicators()
    workers = max(1, int(args.workers))

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=min(workers, len(indicators))) as ex:
        futs = [ex.submit(_run_one, ind, pairs, args.bucket_time) for ind in indicators]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda x: x["indicator"])

    now = datetime.now(timezone.utc)
    out_dir = Path(__file__).resolve().parents[1] / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"all_signal_producers_{now.strftime('%Y%m%dT%H%M%SZ')}.json"

    payload = {
        "generated_at_utc": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "pairs": pairs,
        "workers": workers,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2))

    ready_rows: list[list[Any]] = []
    signal_rows: list[list[Any]] = []
    any_missing = False

    for res in results:
        indicator = res["indicator"]
        for row in res["results"]:
            dec = row.get("decision", {}) or {}
            any_missing = any_missing or row["missing_count"] > 0
            ready_rows.append(
                [
                    indicator,
                    row["pair"],
                    row["status"],
                    row["required_count"],
                    row["present_count"],
                    row["missing_count"],
                ]
            )
            signal_rows.append(
                [
                    indicator,
                    row["pair"],
                    dec.get("signal"),
                    dec.get("triggered"),
                    (row.get("calc") or {}).get("v1"),
                    dec.get("reason"),
                ]
            )

    if args.pretty:
        print(f"output={out_path}")
        print()
        print(table(["indicator", "pair", "status", "required", "present", "missing"], ready_rows))
        print()
        print(table(["indicator", "pair", "signal", "triggered", "v1", "reason"], signal_rows))
    else:
        print(json.dumps({"output": str(out_path), "any_missing": any_missing}, indent=2))

    return 1 if args.strict and any_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
