#!/usr/bin/env python3
"""
Backfill indicators.synthetic_backtest with engine indicator signals.

Usage:
    python backfill_synthetic_backtest.py
    python backfill_synthetic_backtest.py --workers 8
    python backfill_synthetic_backtest.py --limit 10 --dry-run
    python backfill_synthetic_backtest.py --bucket-time 2026-02-10T13:00:00Z
    python backfill_synthetic_backtest.py --indicator rsi_velocity_5m
    python backfill_synthetic_backtest.py --indicator rsi_velocity_5m --workers 8
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timezone
from pathlib import Path
from typing import Any

# engine.py lives in the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import (
    EVALUATORS,
    build_db_url,
    evaluate_indicator,
    iso_z,
    load_env,
    parse_dt,
    psql_json,
)

# ── Config ────────────────────────────────────────────────────────────────────

PAIRS = ["BTC-USD", "ETH-USD"]

# Indicators that have columns in synthetic_backtest (window signals deferred)
BACKTEST_INDICATORS = [
    "rsi_velocity_5m",
    "mtf_signed_efficiency_ratio",
    "multitimeframe_trend_confluence",
    "atr_normalized_reversal_pressure",
    "window_edge_57to01_nonrolling",
    "cvd_price_divergence_velocity",
    "order_flow_acceleration_regime",
    "early_momentum_divergence_score",
    "early_impulse_liquidity_alignment_2m",
    "oi_funding_impulse_confirmation_2m",
]

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db_url() -> str:
    project_root = Path(__file__).resolve().parents[2]
    env = load_env(project_root)
    return build_db_url(env)


def get_bucket_times(db_url: str, limit: int | None = None) -> list[str]:
    """Return all distinct bucket_times from synthetic_backtest, oldest first."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    rows = psql_json(db_url, f"""
        SELECT DISTINCT bucket_time::text AS bt
        FROM indicators.synthetic_backtest
        ORDER BY 1
        {limit_clause}
    """)
    return [r["bt"] for r in rows]


def psql_exec(db_url: str, sql: str) -> None:
    """Execute a DML statement via psql subprocess."""
    env = dict(os.environ)
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    env.setdefault("PGOPTIONS", "-c statement_timeout=30000")
    cmd = ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-A", "-t", "-c", sql]
    proc = subprocess.run(cmd, text=True, env=env, capture_output=True)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)


# ── Core logic ────────────────────────────────────────────────────────────────

def evaluate_bucket(args: tuple[str, str, list[str]]) -> dict[str, Any]:
    """
    Worker function: run the given indicators for one bucket_time.
    Returns a dict ready for build_update_sql().
    """
    db_url, bucket_time_str, indicators = args
    results: dict[str, dict[str, Any]] = {}  # indicator -> pair -> {signal, v1}

    for indicator in indicators:
        try:
            payload = evaluate_indicator(indicator, PAIRS, bucket_time_str)
            by_pair: dict[str, Any] = {}
            for sig in payload.get("signals", []):
                by_pair[sig["pair"]] = {
                    "signal": sig.get("signal"),
                    "triggered": bool(sig.get("triggered")),
                    "v1": sig.get("v1"),
                }
            results[indicator] = by_pair
        except Exception as exc:
            # Log but don't abort — missing data for some indicators is expected
            results[indicator] = {p: {"signal": "error", "triggered": False, "v1": None} for p in PAIRS}
            print(f"  [WARN] {indicator} @ {bucket_time_str}: {exc}", flush=True)

    return {"bucket_time": bucket_time_str, "results": results}


def build_update_sql(bucket_result: dict[str, Any], indicators: list[str] | None = None) -> str | None:
    """
    Build a single UPDATE statement for one bucket_time.
    Only sets columns where a signal actually fired (up/down).
    Returns None if nothing fired.
    """
    bucket_time = bucket_result["bucket_time"]
    results = bucket_result["results"]
    active_indicators = indicators if indicators is not None else BACKTEST_INDICATORS

    set_clauses: list[str] = []
    for indicator in active_indicators:
        by_pair = results.get(indicator, {})
        for pair in PAIRS:
            sig_data = by_pair.get(pair, {})
            signal = sig_data.get("signal", "")
            v1 = sig_data.get("v1")
            triggered = sig_data.get("triggered", False)

            col_dir = f'"{indicator}_{pair}"'
            col_val = f'"{indicator}_{pair}_VALUE"'

            if triggered and signal in ("up", "down"):
                set_clauses.append(f"{col_dir} = {_sql_str(signal)}")
                if v1 is not None:
                    set_clauses.append(f"{col_val} = {float(v1)}")
            # no_signal / missing_inputs / error → leave NULL (don't add to SET)

    if not set_clauses:
        return None

    set_str = ",\n    ".join(set_clauses)
    return f"""
UPDATE indicators.synthetic_backtest
SET
    {set_str}
WHERE bucket_time = {_sql_ts(bucket_time)}::timestamptz;
""".strip()


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_ts(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backfill synthetic_backtest with engine indicator signals.")
    ap.add_argument("--workers", type=int, default=4,
                    help="Parallel workers across bucket_times (default: 4)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only process the first N bucket_times (for testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print UPDATE SQL without executing")
    ap.add_argument("--bucket-time", default=None,
                    help="Process a single specific bucket_time (UTC ISO string)")
    ap.add_argument("--indicator", default=None,
                    help=f"Run only this indicator (one of: {', '.join(BACKTEST_INDICATORS)})")
    return ap.parse_args()


def _fired_summary(result: dict[str, Any], indicators: list[str]) -> str:
    """Return a compact summary of signals that fired, e.g. 'BTC=up(0.432) ETH=no_signal'."""
    parts = []
    for ind in indicators:
        by_pair = result["results"].get(ind, {})
        for pair in PAIRS:
            sig_data = by_pair.get(pair, {})
            if sig_data.get("triggered"):
                v1 = sig_data.get("v1")
                v_str = f"({v1:.4f})" if v1 is not None else ""
                short_pair = pair.split("-")[0]  # BTC / ETH
                parts.append(f"{short_pair}={sig_data['signal']}{v_str}")
    return ", ".join(parts) if parts else "no signals"


def main() -> int:
    args = parse_args()
    db_url = get_db_url()

    # Resolve active indicator list
    if args.indicator:
        if args.indicator not in BACKTEST_INDICATORS:
            print(f"ERROR: unknown indicator '{args.indicator}'. Valid: {', '.join(BACKTEST_INDICATORS)}")
            return 1
        active_indicators = [args.indicator]
        print(f"Running single indicator: {args.indicator}", flush=True)
    else:
        active_indicators = BACKTEST_INDICATORS

    if args.bucket_time:
        bucket_times = [args.bucket_time]
    else:
        print("Fetching distinct bucket_times from synthetic_backtest...", flush=True)
        bucket_times = get_bucket_times(db_url, limit=args.limit)
        print(f"  Found {len(bucket_times)} distinct bucket_times to process.", flush=True)

    total = len(bucket_times)
    done = 0
    updated = 0
    skipped = 0
    errors = 0

    worker_args = [(db_url, bt, active_indicators) for bt in bucket_times]
    workers = max(1, min(args.workers, total))

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(evaluate_bucket, wa): wa[1] for wa in worker_args}
        for fut in as_completed(futs):
            bucket_time = futs[fut]
            done += 1
            try:
                result = fut.result()
                sql = build_update_sql(result, active_indicators)
                if sql is None:
                    skipped += 1
                    print(f"[{done}/{total}] {bucket_time} → no signals fired, skipped", flush=True)
                elif args.dry_run:
                    summary = _fired_summary(result, active_indicators)
                    print(f"[{done}/{total}] {bucket_time} → DRY RUN ({summary}):")
                    print(sql)
                else:
                    psql_exec(db_url, sql)
                    updated += 1
                    summary = _fired_summary(result, active_indicators)
                    print(f"[{done}/{total}] {bucket_time} → updated ({summary})", flush=True)
            except Exception as exc:
                errors += 1
                print(f"[{done}/{total}] {bucket_time} → ERROR: {exc}", flush=True)

    print()
    print(f"Done. {updated} updated, {skipped} skipped (no signals), {errors} errors out of {total} bucket_times.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
