"""
TDD tests for backfill_v2.

RED phase: all tests fail with ImportError because fast_db.py / runner.py don't exist yet.
GREEN phase: all tests pass once implementation is in place.

Run:
    cd syn-final/scripts
    python3 -m pytest backfill_v2/tests/ -v -s
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
KNOWN_BUCKET = "2026-02-03 17:00:00+00"  # CVD fired BTC=up, ETH=up here
SPEED_BUCKETS = [
    "2026-02-01 00:30:00+00",
    "2026-02-01 01:00:00+00",
    "2026-02-01 01:30:00+00",
    "2026-02-01 02:00:00+00",
    "2026-02-01 02:30:00+00",
]
SPEED_INDICATOR = "rsi_velocity_5m"

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1 — fast_db sets DB_QUERY_DRIVER=psycopg2 in this process
# ═══════════════════════════════════════════════════════════════════════════════

def test_fast_db_sets_psycopg2_driver():
    """Fails RED: ImportError. GREEN: driver is 'psycopg2' after import."""
    import backfill_v2.fast_db  # noqa: F401
    assert os.environ.get("DB_QUERY_DRIVER") == "psycopg2", (
        f"Expected 'psycopg2', got '{os.environ.get('DB_QUERY_DRIVER')}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2 — get_db_url returns a valid PostgreSQL URL
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_db_url_returns_postgresql_url():
    """Fails RED: ImportError. GREEN: URL starts with 'postgresql://'."""
    from backfill_v2.fast_db import get_db_url
    url = get_db_url()
    assert url.startswith("postgresql://"), f"Unexpected URL: {url!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3 — psycopg2 actually connects to Supabase
# ═══════════════════════════════════════════════════════════════════════════════

def test_psycopg2_connects_to_supabase():
    """Fails RED: ImportError. GREEN: real connection returns a row count > 0."""
    import psycopg2
    from backfill_v2.fast_db import get_db_url
    conn = psycopg2.connect(get_db_url(), connect_timeout=10)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM indicators.synthetic_backtest")
        row = cur.fetchone()
    conn.close()
    assert row is not None and row[0] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4 — runner.py exports evaluate_bucket_v2 and run_backfill
# ═══════════════════════════════════════════════════════════════════════════════

def test_runner_exports_expected_symbols():
    """Fails RED: ImportError. GREEN: both callables exist."""
    from backfill_v2.runner import evaluate_bucket_v2, run_backfill
    assert callable(evaluate_bucket_v2)
    assert callable(run_backfill)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5 — zero subprocess.run calls during evaluation (psycopg2 only)
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_subprocess_calls_in_psycopg2_mode():
    """
    Fails RED: ImportError.
    GREEN: subprocess.run must NEVER be called when DB_QUERY_DRIVER=psycopg2.
    If it is called, it means psql subprocess fallback is still happening.
    """
    from backfill_v2.fast_db import get_db_url
    from backfill_v2.runner import evaluate_bucket_v2
    db_url = get_db_url()

    with patch("subprocess.run", side_effect=AssertionError("subprocess.run called — psycopg2 not being used")):
        result = evaluate_bucket_v2((db_url, KNOWN_BUCKET, [SPEED_INDICATOR]))

    assert "results" in result
    assert SPEED_INDICATOR in result["results"]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6 — results match psql mode for same bucket_time
# ═══════════════════════════════════════════════════════════════════════════════

def test_results_match_psql_for_known_bucket():
    """
    Fails RED: ImportError.
    GREEN: psycopg2 path and psql path must return identical signals.
    This proves the fast engine does not change indicator logic.
    """
    from backfill_v2.fast_db import get_db_url
    from backfill_v2.runner import evaluate_bucket_v2
    from engine import evaluate_indicator

    db_url = get_db_url()
    indicator = "cvd_price_divergence_velocity"
    pairs = ["BTC-USD", "ETH-USD"]

    # psycopg2 mode (via runner)
    fast = evaluate_bucket_v2((db_url, KNOWN_BUCKET, [indicator]))

    # psql mode (temporarily switch driver back, re-run)
    prev = os.environ.get("DB_QUERY_DRIVER")
    os.environ["DB_QUERY_DRIVER"] = "psql"
    try:
        psql_payload = evaluate_indicator(indicator, pairs, KNOWN_BUCKET)
    finally:
        if prev is not None:
            os.environ["DB_QUERY_DRIVER"] = prev
        else:
            os.environ.pop("DB_QUERY_DRIVER", None)

    for sig in psql_payload.get("signals", []):
        pair = sig["pair"]
        fast_sig = fast["results"].get(indicator, {}).get(pair, {})
        assert fast_sig.get("signal") == sig.get("signal"), (
            f"{pair}: signal mismatch fast={fast_sig.get('signal')!r} vs psql={sig.get('signal')!r}"
        )
        assert fast_sig.get("triggered") == sig.get("triggered"), (
            f"{pair}: triggered mismatch fast={fast_sig.get('triggered')} vs psql={sig.get('triggered')}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7 — ThreadPoolExecutor + psycopg2 is measurably faster than ProcessPool + psql
# ═══════════════════════════════════════════════════════════════════════════════

def test_psycopg2_faster_than_psql_per_query():
    """
    Fails RED: ImportError.
    GREEN: psycopg2 persistent pool must be ≥3x faster than psql subprocess
    on a per-query basis.

    Design rationale for the benchmark:
      - Cache is disabled by patching engine._PSQL_CACHE_TTL_SEC = 0.
        This causes psql_json() to skip all caching/inflight logic and hit the
        real transport for every single call — no warm/cold asymmetry.
      - Sequential (no thread/process pools) so there is zero ProcessPoolExecutor
        startup overhead and no worker-process fail-open ambiguity.
      - Both groups use the same tiny query, same DB, same N=5 calls.
      - Driver is switched via os.environ["DB_QUERY_DRIVER"] which _db_query_driver()
        reads at call time (not module load time).

    True measured speedup (confirmed in diagnostics): ~7x.
    We assert ≥3x as a conservative, reliable threshold.
    """
    import engine
    from backfill_v2.fast_db import get_db_url

    db_url = get_db_url()
    n = 5
    # Minimal query — exercises transport only, not indicator logic
    sql = (
        "SELECT bucket_time FROM indicators.synthetic_backtest "
        "ORDER BY bucket_time LIMIT 1"
    )

    # Disable cache: psql_json skips the entire cache/inflight block when TTL <= 0
    orig_ttl = engine._PSQL_CACHE_TTL_SEC
    engine._PSQL_CACHE_TTL_SEC = 0.0
    engine._PSQL_CACHE.clear()

    try:
        # --- psycopg2: persistent connection pool, no subprocess ---
        # Pool is already warm from earlier tests (test_psycopg2_connects_to_supabase,
        # test_no_subprocess_calls_in_psycopg2_mode, test_results_match_psql_for_known_bucket).
        os.environ["DB_QUERY_DRIVER"] = "psycopg2"
        t0 = time.perf_counter()
        for _ in range(n):
            engine.psql_json(db_url, sql)
        psycopg2_elapsed = time.perf_counter() - t0

        # --- psql subprocess: one new process per query ---
        os.environ["DB_QUERY_DRIVER"] = "psql"
        t0 = time.perf_counter()
        for _ in range(n):
            engine.psql_json(db_url, sql)
        psql_elapsed = time.perf_counter() - t0

    finally:
        engine._PSQL_CACHE_TTL_SEC = orig_ttl
        os.environ["DB_QUERY_DRIVER"] = "psycopg2"  # restore fast_db default

    speedup = psql_elapsed / max(psycopg2_elapsed, 0.001)
    print(
        f"\n  psycopg2 ({n} queries): {psycopg2_elapsed:.2f}s "
        f"({psycopg2_elapsed / n * 1000:.0f} ms/query)"
    )
    print(
        f"  psql     ({n} queries): {psql_elapsed:.2f}s "
        f"({psql_elapsed / n * 1000:.0f} ms/query)"
    )
    print(f"  Speedup: {speedup:.1f}x")
    assert speedup >= 3.0, (
        f"Expected ≥3x speedup, got {speedup:.1f}x "
        f"(psycopg2={psycopg2_elapsed:.2f}s, psql={psql_elapsed:.2f}s)"
    )
