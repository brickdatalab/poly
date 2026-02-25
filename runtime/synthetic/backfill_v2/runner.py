"""
runner.py — fast psycopg2-backed backfill for indicators.synthetic_backtest.

Key differences from backfill_synthetic_backtest.py:
  - psycopg2 persistent connection pool (no subprocess per query)
  - ThreadPoolExecutor (threads share one pool + cache)
  - Zero subprocess.run calls during evaluation or updates

Usage:
    cd syn-final/scripts
    python3 -m backfill_v2.runner --indicator rsi_velocity_5m --workers 8
    python3 -m backfill_v2.runner --indicator rsi_velocity_5m --dry-run
"""
from __future__ import annotations

# fast_db MUST be the very first import — sets DB_QUERY_DRIVER=psycopg2
# before engine.py executes any _db_query_driver() calls in this process.
import backfill_v2.fast_db as _fast_db  # noqa: F401 (side-effect import)

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from engine import (
    _get_pg_pool,
    evaluate_indicator,
    psql_json,
)

PAIRS = ["BTC-USD", "ETH-USD"]

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


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_bucket_times(db_url: str, limit: int | None = None) -> list[str]:
    rows = psql_json(db_url, f"""
        SELECT DISTINCT bucket_time::text AS bt
        FROM indicators.synthetic_backtest
        ORDER BY 1
        {f'LIMIT {limit}' if limit else ''}
    """)
    return [r["bt"] for r in rows]


def _exec_update(db_url: str, sql: str) -> None:
    """Execute a DML statement via psycopg2 using engine's shared connection pool."""
    pool = _get_pg_pool(db_url)
    conn = pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        pool.putconn(conn)


# ── Core evaluation ────────────────────────────────────────────────────────────

def evaluate_bucket_v2(args: tuple[str, str, list[str]]) -> dict[str, Any]:
    """
    Evaluate indicators for one bucket_time using psycopg2 (zero subprocess calls).
    Signature is compatible with ThreadPoolExecutor.map().
    """
    db_url, bucket_time_str, indicators = args
    results: dict[str, dict[str, Any]] = {}

    for indicator in indicators:
        try:
            payload = evaluate_indicator(indicator, PAIRS, bucket_time_str)
            by_pair: dict[str, Any] = {}
            for sig in payload.get("signals", []):
                by_pair[sig["pair"]] = {
                    "signal":    sig.get("signal"),
                    "triggered": bool(sig.get("triggered")),
                    "v1":        sig.get("v1"),
                }
            results[indicator] = by_pair
        except Exception as exc:
            results[indicator] = {
                p: {"signal": "error", "triggered": False, "v1": None} for p in PAIRS
            }
            print(f"  [WARN] {indicator} @ {bucket_time_str}: {exc}", flush=True)

    return {"bucket_time": bucket_time_str, "results": results}


# ── SQL builder ────────────────────────────────────────────────────────────────

def build_update_sql(bucket_result: dict[str, Any], indicators: list[str] | None = None) -> str | None:
    bucket_time = bucket_result["bucket_time"]
    results     = bucket_result["results"]
    active      = indicators or BACKTEST_INDICATORS
    set_clauses: list[str] = []

    for indicator in active:
        by_pair = results.get(indicator, {})
        for pair in PAIRS:
            sig      = by_pair.get(pair, {})
            signal   = sig.get("signal", "")
            v1       = sig.get("v1")
            triggered = sig.get("triggered", False)
            col_dir  = f'"{indicator}_{pair}"'
            col_val  = f'"{indicator}_{pair}_VALUE"'
            if triggered and signal in ("up", "down"):
                set_clauses.append(f"{col_dir} = '{signal}'")
                if v1 is not None:
                    set_clauses.append(f"{col_val} = {float(v1)}")

    if not set_clauses:
        return None

    return (
        "UPDATE indicators.synthetic_backtest\nSET\n    "
        + ",\n    ".join(set_clauses)
        + f"\nWHERE bucket_time = '{bucket_time}'::timestamptz;"
    )


def _fired_summary(result: dict[str, Any], indicators: list[str]) -> str:
    parts = []
    for ind in indicators:
        for pair in PAIRS:
            sig = result["results"].get(ind, {}).get(pair, {})
            if sig.get("triggered"):
                v1    = sig.get("v1")
                v_str = f"({v1:.4f})" if v1 is not None else ""
                parts.append(f"{pair.split('-')[0]}={sig['signal']}{v_str}")
    return ", ".join(parts) if parts else "no signals"


# ── Public API ─────────────────────────────────────────────────────────────────

def run_backfill(
    db_url: str,
    bucket_times: list[str],
    indicators: list[str],
    workers: int = 8,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Run the backfill. Returns (updated, skipped, errors)."""
    total   = len(bucket_times)
    updated = skipped = errors = 0
    worker_args = [(db_url, bt, indicators) for bt in bucket_times]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(evaluate_bucket_v2, wa): wa[1] for wa in worker_args}
        done = 0
        for fut in as_completed(futs):
            bt   = futs[fut]
            done += 1
            try:
                result = fut.result()
                sql    = build_update_sql(result, indicators)
                if sql is None:
                    skipped += 1
                    print(f"[{done}/{total}] {bt} → no signals fired, skipped", flush=True)
                elif dry_run:
                    skipped += 1
                    print(f"[{done}/{total}] {bt} → DRY RUN ({_fired_summary(result, indicators)})")
                else:
                    _exec_update(db_url, sql)
                    updated += 1
                    print(f"[{done}/{total}] {bt} → updated ({_fired_summary(result, indicators)})", flush=True)
            except Exception as exc:
                errors += 1
                print(f"[{done}/{total}] {bt} → ERROR: {exc}", flush=True)

    return updated, skipped, errors


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Fast psycopg2 backfill for indicators.synthetic_backtest.")
    ap.add_argument("--workers",    type=int, default=8)
    ap.add_argument("--limit",      type=int, default=None)
    ap.add_argument("--dry-run",    action="store_true")
    ap.add_argument("--bucket-time", default=None)
    ap.add_argument("--indicator",  default=None,
                    help=f"Single indicator. One of: {', '.join(BACKTEST_INDICATORS)}")
    args = ap.parse_args()

    import backfill_v2.fast_db as fast_db
    db_url = fast_db.get_db_url()
    fast_db.verify_psycopg2(db_url)
    print(f"✓ psycopg2 connected  (driver={os.environ.get('DB_QUERY_DRIVER')})", flush=True)

    if args.indicator:
        if args.indicator not in BACKTEST_INDICATORS:
            print(f"ERROR: unknown indicator '{args.indicator}'")
            return 1
        active = [args.indicator]
        print(f"Running single indicator: {args.indicator}", flush=True)
    else:
        active = BACKTEST_INDICATORS

    if args.bucket_time:
        bucket_times = [args.bucket_time]
    else:
        print("Fetching bucket_times...", flush=True)
        bucket_times = get_bucket_times(db_url, limit=args.limit)
        print(f"  Found {len(bucket_times)} distinct bucket_times.", flush=True)

    updated, skipped, errors = run_backfill(db_url, bucket_times, active,
                                            workers=args.workers, dry_run=args.dry_run)
    print(f"\nDone. {updated} updated, {skipped} skipped, {errors} errors out of {len(bucket_times)} bucket_times.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
