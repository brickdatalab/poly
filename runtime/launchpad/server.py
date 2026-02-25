#!/usr/bin/env python3
"""
Signal Launchpad Server
=======================
Runs real indicator scripts and serves the dashboard.

Usage:
    cd /Users/vitolo/Desktop/projects/poly
    python3 server.py

Then open http://localhost:8888
"""
from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Paths ──
APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "runtime" / "synthetic"

# Add scripts dir so we can import engine
sys.path.insert(0, str(SCRIPTS_DIR))

from engine import EVALUATORS, build_db_url, evaluate_indicator, floor_15m, iso_z, load_env, psql_json, quote  # noqa: E402

# ── Disabled indicators (skip these entirely) ──
DISABLED = {
    "rsi_volatility_normalized_velocity",
}

# ── Stage overrides for server scheduling ──
STAGE_OVERRIDES = {
    "early_momentum_divergence_score": 2,
}


def stage_for_indicator(name: str, default_phase: int) -> int:
    return int(STAGE_OVERRIDES.get(name, default_phase))


# ── Indicator grouping by decision_phase_minutes ──
T1_NAMES = sorted(
    n
    for n, s in EVALUATORS.items()
    if stage_for_indicator(n, s.decision_phase_minutes) == 1 and n not in DISABLED
)
T2_NAMES = sorted(
    n
    for n, s in EVALUATORS.items()
    if stage_for_indicator(n, s.decision_phase_minutes) == 2 and n not in DISABLED
)

PAIRS = ["BTC-USD", "ETH-USD"]

WINDOW_SCRIPTS = [
    {
        "id": "window_up_signal",
        "path": REPO_ROOT / "runtime" / "synthetic" / "window" / "t2_window_up_signal.py",
        "direction": "up",
    },
    {
        "id": "window_down_signal",
        "path": REPO_ROOT / "runtime" / "synthetic" / "window" / "t2_window_down_signal.py",
        "direction": "down",
    },
]

# ── Helpers ──

def run_one_indicator(name: str, pairs: list[str], bucket_iso: str) -> tuple[str, dict | None, str | None]:
    """Run a single engine indicator. Returns (name, payload, error)."""
    try:
        payload = evaluate_indicator(name, pairs, bucket_iso)
        return (name, payload, None)
    except Exception as e:
        return (name, None, str(e))


def run_window_script(ws: dict) -> dict[str, Any]:
    """Run a window script as subprocess, parse its sigma output."""
    try:
        result = subprocess.run(
            [sys.executable, str(ws["path"])],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            return {"id": ws["id"], "direction": ws["direction"], "results": [],
                    "error": result.stderr.strip() or f"exit code {result.returncode}"}

        results = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            # Match "ETH-USD: +0.75σ"
            m = re.match(r'^(\S+):\s*\+(\d+\.?\d*)σ$', line)
            if m:
                results.append({"pair": m.group(1), "bestSigma": float(m.group(2)), "triggered": True})
                continue
            # Match "ETH-USD: none"
            m2 = re.match(r'^(\S+):\s*none$', line)
            if m2:
                results.append({"pair": m2.group(1), "bestSigma": None, "triggered": False})

        return {"id": ws["id"], "direction": ws["direction"], "results": results, "error": None}
    except Exception as e:
        return {"id": ws["id"], "direction": ws["direction"], "results": [], "error": str(e)}


def extract_engine_signals(name: str, payload: dict, phase: int) -> list[dict]:
    """Extract triggered signal objects from an engine indicator payload."""
    signals = []
    for r in payload.get("results", []):
        dec = r.get("decision") or {}
        calc = r.get("calc") or {}
        signals.append({
            "type": "engine",
            "indicator": payload["indicator"],
            "label": payload["indicator"],
            "pair": r["pair"],
            "phase": phase,
            "signal": dec.get("signal", "no_signal"),
            "triggered": bool(dec.get("triggered")),
            "v1": calc.get("v1"),
            "reason": dec.get("reason", ""),
            "context": dec.get("context", {}),
            "bucket_time": payload.get("bucket_time_utc", ""),
        })
    return signals


def extract_window_signals(result: dict, bucket_iso: str) -> list[dict]:
    """Extract triggered signal objects from a window script result."""
    signals = []
    for r in result.get("results", []):
        signals.append({
            "type": "window",
            "indicator": result["id"],
            "label": result["id"],
            "pair": r["pair"],
            "direction": result["direction"],
            "signal": f"sigma_{result['direction']}",
            "triggered": bool(r.get("triggered")),
            "bestSigma": r.get("bestSigma"),
            "bucket_time": bucket_iso,
        })
    return signals


# ── Fire functions ──

def fire_engine_batch(names: list[str], phase: int) -> dict:
    """Run engine indicators in parallel. Returns {signals, errors, bucket, coverage}."""
    now = datetime.now(timezone.utc)
    bucket = floor_15m(now)
    bucket_iso = iso_z(bucket)

    all_signals: list[dict] = []
    errors: list[dict] = []
    coverage: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(6, len(names))) as pool:
        futures = {pool.submit(run_one_indicator, n, PAIRS, bucket_iso): n for n in names}
        for fut in as_completed(futures):
            name = futures[fut]
            ind_name, payload, err = fut.result()
            if err:
                errors.append({"indicator": name, "error": err})
                _log(f"  ✗ {name}: {err[:80]}")
                continue
            pair_rows = []
            for row in payload.get("results", []):
                pair_rows.append({
                    "pair": row.get("pair"),
                    "status": row.get("status"),
                    "required_count": row.get("required_count"),
                    "present_count": row.get("present_count"),
                    "missing_count": row.get("missing_count"),
                    "missing_inputs": row.get("missing_inputs", []),
                })
            coverage.append({
                "indicator": payload.get("indicator", name),
                "phase": phase,
                "pairs": pair_rows,
            })
            sigs = extract_engine_signals(name, payload, phase)
            triggered = [s for s in sigs if s["triggered"]]
            for s in sigs:
                pair_label = f"{s['pair']}={s['signal']}"
                if s["triggered"] and s.get("v1") is not None:
                    pair_label += f"({s['v1']:.4f})"
                _log(f"  {'✓' if s['triggered'] else '·'} {name} {pair_label}")
            all_signals.extend(sigs)

    return {"signals": all_signals, "errors": errors, "bucket": bucket_iso, "coverage": coverage}


def fire_window_batch() -> dict:
    """Run window scripts in parallel. Returns {signals, errors, bucket, coverage}."""
    now = datetime.now(timezone.utc)
    bucket = floor_15m(now)
    bucket_iso = iso_z(bucket)

    all_signals: list[dict] = []
    errors: list[dict] = []
    coverage: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(run_window_script, ws): ws for ws in WINDOW_SCRIPTS}
        for fut in as_completed(futures):
            ws = futures[fut]
            result = fut.result()
            if result.get("error"):
                errors.append({"indicator": result["id"], "error": result["error"]})
                _log(f"  ✗ {result['id']}: {result['error'][:80]}")
                continue
            coverage.append({
                "indicator": result.get("id"),
                "direction": result.get("direction"),
                "pairs": [
                    {
                        "pair": r.get("pair"),
                        "triggered": bool(r.get("triggered")),
                        "best_sigma": r.get("bestSigma"),
                    }
                    for r in result.get("results", [])
                ],
            })
            sigs = extract_window_signals(result, bucket_iso)
            for r in result.get("results", []):
                sigma_str = f"+{r['bestSigma']:.2f}σ" if r.get("bestSigma") is not None else "none"
                _log(f"  {'✓' if r['triggered'] else '·'} {result['id']} {r['pair']}={sigma_str}")
            all_signals.extend(sigs)

    return {"signals": all_signals, "errors": errors, "bucket": bucket_iso, "coverage": coverage}


def _log(msg: str):
    print(msg, flush=True)


def _coverage_not_ready(coverage_row: dict[str, Any]) -> bool:
    pairs = coverage_row.get("pairs", [])
    if not pairs:
        return True
    return any((p.get("status") != "ready") for p in pairs)


def _freshness_gate_enabled() -> bool:
    raw = (os.environ.get("ENGINE_ENFORCE_FRESHNESS_GATE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _freshness_thresholds_seconds(phase: int) -> dict[str, float]:
    def _get(name: str, default: float) -> float:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            return default
        try:
            return max(1.0, float(raw))
        except Exception:
            return default

    thresholds = {
        "indicators.ohlcv_1m": _get("ENGINE_GATE_MAX_AGE_OHLCV_1M_SEC", 180.0),
        "indicators.ohlcv_5m": _get("ENGINE_GATE_MAX_AGE_OHLCV_5M_SEC", 3600.0),
        "indicators.ohlcv_15m": _get("ENGINE_GATE_MAX_AGE_OHLCV_15M_SEC", 5400.0),
        "indicators.indicator_values": _get("ENGINE_GATE_MAX_AGE_INDICATOR_VALUES_SEC", 5400.0),
        "indicators.order_book_indicators": _get("ENGINE_GATE_MAX_AGE_ORDERBOOK_SEC", 180.0),
    }
    if phase >= 2:
        thresholds["indicators.oi_features"] = _get("ENGINE_GATE_MAX_AGE_OI_FEATURES_SEC", 5400.0)
    return thresholds


def _run_engine_freshness_gate(phase: int, bucket_iso: str) -> dict[str, Any]:
    if not _freshness_gate_enabled():
        return {"ok": True, "enabled": False, "checked_at_bucket": bucket_iso, "rows": [], "violations": []}

    env = load_env(REPO_ROOT)
    db_url = build_db_url(env)
    thresholds = _freshness_thresholds_seconds(phase)
    pair_sql = ",".join(quote(p) for p in PAIRS)

    sql = f"""
      with src as (
        select 'indicators.ohlcv_1m'::text as source, pair, max(bucket_time) as max_ts
        from indicators.ohlcv_1m where pair in ({pair_sql}) group by pair
        union all
        select 'indicators.ohlcv_5m'::text as source, pair, max(bucket_time) as max_ts
        from indicators.ohlcv_5m where pair in ({pair_sql}) group by pair
        union all
        select 'indicators.ohlcv_15m'::text as source, pair, max(bucket_time) as max_ts
        from indicators.ohlcv_15m where pair in ({pair_sql}) group by pair
        union all
        select 'indicators.indicator_values'::text as source, pair, max(bucket_time) as max_ts
        from indicators.indicator_values where pair in ({pair_sql}) group by pair
        union all
        select 'indicators.order_book_indicators'::text as source, pair, max(captured_at) as max_ts
        from indicators.order_book_indicators where pair in ({pair_sql}) group by pair
        union all
        select 'indicators.oi_features'::text as source, pair, max(bucket_time) as max_ts
        from indicators.oi_features where pair in ({pair_sql}) group by pair
      )
      select
        source,
        pair,
        max_ts,
        extract(epoch from ((now() at time zone 'utc') - max_ts))::float8 as lag_seconds
      from src
    """
    rows = psql_json(db_url, sql)
    filtered_rows = [r for r in rows if r.get("source") in thresholds]
    violations = []
    for row in filtered_rows:
        source = str(row.get("source", ""))
        pair = str(row.get("pair", ""))
        max_ts = row.get("max_ts")
        lag = row.get("lag_seconds")
        try:
            lag_sec = float(lag) if lag is not None else float("inf")
        except Exception:
            lag_sec = float("inf")
        max_allowed = thresholds[source]
        if max_ts is None or lag_sec > max_allowed:
            violations.append(
                {
                    "source": source,
                    "pair": pair,
                    "max_ts": max_ts,
                    "lag_seconds": lag_sec,
                    "max_allowed_seconds": max_allowed,
                }
            )
    return {
        "ok": not violations,
        "enabled": True,
        "checked_at_bucket": bucket_iso,
        "rows": filtered_rows,
        "violations": violations,
    }


def _build_freshness_gate_blocked_result(names: list[str], phase: int, bucket_iso: str, gate: dict[str, Any]) -> dict[str, Any]:
    coverage = []
    signals = []
    reason = "freshness_gate_blocked"
    for name in names:
        pair_rows = []
        for pair in PAIRS:
            pair_rows.append(
                {
                    "pair": pair,
                    "status": reason,
                    "required_count": None,
                    "present_count": None,
                    "missing_count": None,
                    "missing_inputs": [reason],
                }
            )
            signals.append(
                {
                    "type": "engine",
                    "indicator": name,
                    "label": name,
                    "pair": pair,
                    "phase": phase,
                    "signal": "not_ready",
                    "triggered": False,
                    "v1": None,
                    "reason": reason,
                    "context": {"freshness_gate": gate},
                    "bucket_time": bucket_iso,
                }
            )
        coverage.append({"indicator": name, "phase": phase, "pairs": pair_rows})
    return {
        "signals": signals,
        "errors": [],
        "bucket": bucket_iso,
        "coverage": coverage,
        "freshness_gate": gate,
    }


def _merge_engine_batch_results(acc: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    signal_map: dict[tuple[str, str, str], dict[str, Any]] = {
        (s.get("type", "engine"), s.get("indicator", ""), s.get("pair", "")): s
        for s in acc.get("signals", [])
    }
    for s in batch.get("signals", []):
        key = (s.get("type", "engine"), s.get("indicator", ""), s.get("pair", ""))
        signal_map[key] = s

    coverage_map: dict[str, dict[str, Any]] = {c.get("indicator", ""): c for c in acc.get("coverage", [])}
    for c in batch.get("coverage", []):
        coverage_map[c.get("indicator", "")] = c

    error_map: dict[str, dict[str, Any]] = {e.get("indicator", ""): e for e in acc.get("errors", [])}
    for c in batch.get("coverage", []):
        indicator = c.get("indicator", "")
        if indicator:
            error_map.pop(indicator, None)
    for e in batch.get("errors", []):
        indicator = e.get("indicator", "")
        if indicator:
            error_map[indicator] = e

    return {
        "signals": list(signal_map.values()),
        "errors": list(error_map.values()),
        "bucket": batch.get("bucket") or acc.get("bucket"),
        "coverage": list(coverage_map.values()),
    }


def fire_engine_batch_with_not_ready_retries(
    names: list[str],
    phase: int,
    retry_interval_sec: float | None = None,
    max_wait_sec: float | None = None,
) -> dict[str, Any]:
    bucket_iso = iso_z(floor_15m(datetime.now(timezone.utc)))
    gate = _run_engine_freshness_gate(phase, bucket_iso)
    if not gate.get("ok", False):
        violations = gate.get("violations", [])
        _log(f"  ✗ freshness_gate blocked phase={phase} batch ({len(violations)} violations)")
        for v in violations[:12]:
            lag = v.get("lag_seconds")
            max_allowed = v.get("max_allowed_seconds")
            _log(f"    · {v.get('source')} {v.get('pair')} lag={lag:.1f}s>{max_allowed:.1f}s")
        return _build_freshness_gate_blocked_result(names, phase, bucket_iso, gate)

    retry_interval = float(
        retry_interval_sec if retry_interval_sec is not None else os.environ.get("ENGINE_NOT_READY_RETRY_INTERVAL_SEC", "5")
    )
    retry_interval = max(0.0, retry_interval)
    max_wait = float(max_wait_sec if max_wait_sec is not None else os.environ.get("ENGINE_NOT_READY_RETRY_MAX_WAIT_SEC", "45"))
    max_wait = max(0.0, max_wait)

    combined = fire_engine_batch(names, phase)
    coverage_map = {c.get("indicator", ""): c for c in combined.get("coverage", [])}
    error_map = {e.get("indicator", ""): e for e in combined.get("errors", [])}

    pending = {
        n for n in names
        if (n in coverage_map and _coverage_not_ready(coverage_map[n])) or (n in error_map)
    }
    if not pending or max_wait <= 0:
        return combined

    deadline = time.monotonic() + max_wait
    while pending and time.monotonic() < deadline:
        time.sleep(retry_interval)
        retry_batch = fire_engine_batch(sorted(pending), phase)
        combined = _merge_engine_batch_results(combined, retry_batch)
        coverage_map = {c.get("indicator", ""): c for c in combined.get("coverage", [])}
        error_map = {e.get("indicator", ""): e for e in combined.get("errors", [])}
        pending = {
            n for n in names
            if (n in coverage_map and _coverage_not_ready(coverage_map[n])) or (n in error_map)
        }
    return combined


# ── HTTP Handler ──

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(APP_ROOT / "launchpad.html", "text/html")
        elif self.path == "/api/health":
            self._json({"status": "ok", "t1": T1_NAMES, "t2": T2_NAMES,
                         "pairs": PAIRS, "windows": [w["id"] for w in WINDOW_SCRIPTS]})
        elif self.path == "/api/fire/t1":
            self._handle_fire_t1()
        elif self.path == "/api/fire/t2":
            self._handle_fire_t2()
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def _handle_fire_t1(self):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        _log(f"\n[{ts}] ── Firing T+1m ({len(T1_NAMES)} indicators) ──")
        result = fire_engine_batch_with_not_ready_retries(T1_NAMES, 1)
        triggered = [s for s in result["signals"] if s["triggered"]]
        _log(f"  → {len(triggered)} triggered, {len(result['errors'])} errors")
        self._json(result)

    def _handle_fire_t2(self):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        _log(f"\n[{ts}] ── Firing T+2m ({len(T2_NAMES)} indicators) + window scripts ──")
        engine_result = fire_engine_batch_with_not_ready_retries(T2_NAMES, 2)
        window_result = fire_window_batch()
        combined = {
            "signals": engine_result["signals"] + window_result["signals"],
            "errors": engine_result["errors"] + window_result["errors"],
            "bucket": engine_result["bucket"],
            "engine_coverage": engine_result.get("coverage", []),
            "window_coverage": window_result.get("coverage", []),
        }
        e_trig = len([s for s in engine_result["signals"] if s["triggered"]])
        w_trig = len([s for s in window_result["signals"] if s["triggered"]])
        _log(f"  → {e_trig + w_trig} triggered ({e_trig} engine, {w_trig} window), "
             f"{len(combined['errors'])} errors")
        self._json(combined)

    def _json(self, data: dict):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str):
        try:
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, f"File not found: {path.name}")

    def log_message(self, format, *args):
        # Suppress noisy GET logs for fire endpoints (we log our own)
        req = str(args[0]) if args else ""
        if "/api/fire/" in req:
            return
        super().log_message(format, *args)


# ── Main ──

def main():
    port = int(os.environ.get("PORT", 8888))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)

    print("━" * 56)
    print("  Signal Launchpad Server")
    print("━" * 56)
    print(f"  T+1m : {', '.join(T1_NAMES)}")
    print(f"  T+2m : {', '.join(T2_NAMES)}")
    print(f"  Window: {', '.join(w['id'] for w in WINDOW_SCRIPTS)}")
    print(f"  Pairs : {', '.join(PAIRS)}")
    print(f"\n  → http://localhost:{port}")
    print("━" * 56 + "\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
