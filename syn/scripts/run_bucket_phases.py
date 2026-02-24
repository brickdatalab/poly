#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import engine
from run_now_executor import parse_pairs, run_once


def build_phase_run_times(
    bucket: datetime,
    t_plus1_seconds: int = 74,
    t_plus2_seconds: int = 120,
) -> list[dict[str, Any]]:
    return [
        {"phase": "t0", "run_at": bucket},
        {"phase": "t_plus_1", "run_at": bucket + timedelta(seconds=t_plus1_seconds)},
        {"phase": "t_plus_2", "run_at": bucket + timedelta(seconds=t_plus2_seconds)},
    ]


def infer_current_bucket(now_utc: datetime) -> datetime:
    return now_utc.replace(minute=(now_utc.minute // 15) * 15, second=0, microsecond=0)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run phased synthetic executor for one bucket.")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD", help="Comma-separated pairs")
    ap.add_argument("--bucket-time", default=None, help="Explicit bucket_time UTC")
    ap.add_argument("--t-plus1-seconds", type=int, default=74)
    ap.add_argument("--t-plus2-seconds", type=int, default=120)
    ap.add_argument("--pretty", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now(timezone.utc)
    bucket = engine.parse_dt(args.bucket_time) if args.bucket_time else infer_current_bucket(now)
    pairs = parse_pairs(args.pairs)

    phases = build_phase_run_times(bucket, args.t_plus1_seconds, args.t_plus2_seconds)
    records: list[dict[str, Any]] = []

    for p in phases:
        phase = p["phase"]
        run_at: datetime = p["run_at"]
        while True:
            now_utc = datetime.now(timezone.utc)
            wait_sec = (run_at - now_utc).total_seconds()
            if wait_sec <= 0:
                break
            time.sleep(min(wait_sec, 0.25))

        payload = run_once(
            pairs=pairs,
            bucket=bucket,
            max_phase=phase,
        )
        records.append({
            "phase": phase,
            "run_at_utc": engine.iso_z(run_at),
            "executed_at_utc": engine.iso_z(datetime.now(timezone.utc)),
            "status": payload["status"],
            "payload": payload,
        })

        if args.pretty:
            print(f"phase={phase} run_at={engine.iso_z(run_at)} status={payload['status']} timing={payload['timing_seconds']}s")
            for pair, rec in payload["recommendation_by_pair"].items():
                print(f"  {pair}: {rec['recommended']} (up={rec['up_signals']} down={rec['down_signals']})")

    out_dir = Path(__file__).resolve().parents[1] / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"run_bucket_phases_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps({
        "bucket_time_utc": engine.iso_z(bucket),
        "pairs": pairs,
        "phases": records,
    }, indent=2))

    if args.pretty:
        print(f"output={out_path}")

    # Non-zero if final phase still not ready.
    final_status = records[-1]["status"] if records else "not_ready"
    return 0 if final_status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
