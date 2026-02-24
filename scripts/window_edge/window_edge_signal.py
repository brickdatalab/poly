#!/usr/bin/env python3
"""Window-edge boundary momentum signal.

This encodes the discovery:
- Feature: pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100
- Label (from training analysis): 15m candle direction (close@t0+14m vs open@t0)

This module provides:
- Hard, frozen thresholds per pair (BTC-USD, ETH-USD) at sigma levels.
- Expected win-rates (precision) from training for each threshold.
- Helpers to compute pct_diff from `indicators.ohlcv_1m` for a given 15m event start.

Notes:
- Uses `t0+1m` close, so it is only usable if you can decide at/after `t0+1m`.
- SOL intentionally excluded.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


Pair = Literal["BTC-USD", "ETH-USD"]
Direction = Literal["UP", "DOWN"]


@dataclass(frozen=True)
class ThresholdPoint:
    sigma: float
    threshold_pct: float
    expected_accuracy_pct: float
    match_rate_pct: float
    n_match: int


@dataclass(frozen=True)
class Signal:
    pair: Pair
    t0_utc: str
    pct_diff: float
    prediction: Direction | None
    sigma: float | None
    threshold_pct: float | None
    expected_accuracy_pct: float | None
    match_rate_pct: float | None


# Hard thresholds and expected accuracies derived from training schema scan
# (merged across all quarter-hour starts :00/:15/:30/:45).
#
# For UP-side thresholds: condition is pct_diff > threshold_pct.
# For DOWN-side thresholds: condition is pct_diff < threshold_pct (negative).
THRESHOLDS: dict[Pair, dict[str, list[ThresholdPoint]]] = {
    "BTC-USD": {
        "up": [
            ThresholdPoint(0.25, 0.0574382244359396, 58.5421, 28.4210, 30303),
            ThresholdPoint(0.5, 0.1115087125004410, 60.6173, 16.9562, 18079),
            ThresholdPoint(0.75, 0.1655792005649420, 62.1439, 10.5691, 11269),
            ThresholdPoint(1.0, 0.2196496886294430, 64.0346, 6.9367, 7396),
            ThresholdPoint(1.5, 0.3277906647584450, 66.0801, 3.4646, 3694),
            ThresholdPoint(2.0, 0.4359316408874480, 67.2131, 1.9452, 2074),
            ThresholdPoint(3.0, 0.6522135931454520, 70.1970, 0.761569, 812),
            ThresholdPoint(4.0, 0.8684955454034570, 71.6707, 0.387350, 413),
        ],
        "down": [
            ThresholdPoint(0.25, -0.0507027516930629, 57.5036, 29.823113, 31798),
            ThresholdPoint(0.5, -0.1047732397575640, 59.1940, 17.290991, 18436),
            ThresholdPoint(0.75, -0.1588437278220660, 60.6748, 10.508150, 11204),
            ThresholdPoint(1.0, -0.2129142158865670, 61.9601, 6.775337, 7224),
            ThresholdPoint(1.5, -0.3210551920155700, 63.8807, 3.175705, 3386),
            ThresholdPoint(2.0, -0.4291961681445730, 65.5586, 1.721033, 1835),
            ThresholdPoint(3.0, -0.6454781204025780, 67.7467, 0.636829, 679),
            ThresholdPoint(4.0, -0.8617600726605840, 70.5696, 0.296374, 316),
        ],
    },
    "ETH-USD": {
        "up": [
            ThresholdPoint(0.25, 0.0719108856117475, 57.2758, 29.0212, 29227),
            ThresholdPoint(0.5, 0.1398627854981910, 59.3307, 17.5059, 17630),
            ThresholdPoint(0.75, 0.2078146853846350, 61.4931, 11.1063, 11185),
            ThresholdPoint(1.0, 0.2757665852710780, 63.5002, 7.3588, 7411),
            ThresholdPoint(1.5, 0.4116703850439650, 65.7635, 3.6283, 3654),
            ThresholdPoint(2.0, 0.5475741848168520, 68.3227, 2.0187, 2033),
            ThresholdPoint(3.0, 0.8193817843626170, 71.9101, 0.795361, 801),
            ThresholdPoint(4.0, 1.0911893839083900, 70.6030, 0.395198, 398),
        ],
        "down": [
            ThresholdPoint(0.25, -0.0639929141611394, 56.8645, 30.427271, 30643),
            ThresholdPoint(0.5, -0.1319448140475830, 58.0406, 18.060948, 18189),
            ThresholdPoint(0.75, -0.1998967139340260, 59.4044, 10.970221, 11048),
            ThresholdPoint(1.0, -0.2678486138204690, 60.6792, 7.075832, 7126),
            ThresholdPoint(1.5, -0.4037524135933560, 62.5556, 3.349254, 3373),
            ThresholdPoint(2.0, -0.5396562133662420, 64.8261, 1.798250, 1811),
            ThresholdPoint(3.0, -0.8114638129120160, 67.6768, 0.688121, 693),
            ThresholdPoint(4.0, -1.0832714124577900, 67.7419, 0.307818, 310),
        ],
    },
}


def _load_db_url(env_path: Path) -> str:
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def _psql_scalar(db_url: str, sql: str) -> str:
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1]
    cmd = [
        "psql",
        db_url,
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-t",
        "-A",
        "-c",
        sql,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return out


def floor_to_quarter_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")
    m = (dt.minute // 15) * 15
    return dt.replace(minute=m, second=0, microsecond=0)


def compute_pct_diff_from_indicators(db_url: str, pair: Pair, t0: datetime) -> float | None:
    """Returns pct_diff for the event start t0 (15m candle start), or None if data missing."""
    if t0.tzinfo is None:
        raise ValueError("t0 must be timezone-aware")
    t0_iso = t0.astimezone(timezone.utc).isoformat()

    sql = f"""
with pre as (
  select open::float8 as pre_open
  from indicators.ohlcv_1m
  where pair = '{pair}'
    and bucket_time = ('{t0_iso}'::timestamptz - interval '3 minutes')
), post as (
  select close::float8 as post_close
  from indicators.ohlcv_1m
  where pair = '{pair}'
    and bucket_time = ('{t0_iso}'::timestamptz + interval '1 minute')
)
select
  case
    when (select pre_open from pre) is null or (select post_close from post) is null then null::float8
    else (((select post_close from post) - (select pre_open from pre)) / nullif((select pre_open from pre), 0.0)) * 100.0
  end;
"""

    out = _psql_scalar(db_url, sql)
    if out == "":
        return None
    return float(out)


def best_signal_from_pct_diff(pair: Pair, t0_utc: str, pct_diff: float, *, min_sigma: float = 0.25) -> Signal:
    """Pick the strongest (highest sigma) rule that triggers for UP or DOWN.

    If none triggers at or above min_sigma, returns prediction=None.
    """

    pts_up = [p for p in THRESHOLDS[pair]["up"] if p.sigma >= min_sigma]
    pts_dn = [p for p in THRESHOLDS[pair]["down"] if p.sigma >= min_sigma]

    best_up: ThresholdPoint | None = None
    for p in pts_up:
        if pct_diff > p.threshold_pct:
            best_up = p

    best_dn: ThresholdPoint | None = None
    for p in pts_dn:
        if pct_diff < p.threshold_pct:
            best_dn = p

    # Only one side can be true for any pct_diff.
    if best_up is not None:
        return Signal(
            pair=pair,
            t0_utc=t0_utc,
            pct_diff=pct_diff,
            prediction="UP",
            sigma=best_up.sigma,
            threshold_pct=best_up.threshold_pct,
            expected_accuracy_pct=best_up.expected_accuracy_pct,
            match_rate_pct=best_up.match_rate_pct,
        )

    if best_dn is not None:
        return Signal(
            pair=pair,
            t0_utc=t0_utc,
            pct_diff=pct_diff,
            prediction="DOWN",
            sigma=best_dn.sigma,
            threshold_pct=best_dn.threshold_pct,
            expected_accuracy_pct=best_dn.expected_accuracy_pct,
            match_rate_pct=best_dn.match_rate_pct,
        )

    return Signal(
        pair=pair,
        t0_utc=t0_utc,
        pct_diff=pct_diff,
        prediction=None,
        sigma=None,
        threshold_pct=None,
        expected_accuracy_pct=None,
        match_rate_pct=None,
    )


def passed_thresholds(pair: Pair, pct_diff: float, *, min_sigma: float = 0.25) -> dict[str, list[dict[str, float]]]:
    """Return all thresholds passed (at or above min_sigma) for UP and DOWN sides."""

    ups = [p for p in THRESHOLDS[pair]["up"] if p.sigma >= min_sigma and pct_diff > p.threshold_pct]
    dns = [p for p in THRESHOLDS[pair]["down"] if p.sigma >= min_sigma and pct_diff < p.threshold_pct]
    ups.sort(key=lambda p: p.sigma, reverse=True)
    dns.sort(key=lambda p: p.sigma, reverse=True)

    def pack(p: ThresholdPoint) -> dict[str, float]:
        return {
            "sigma": float(p.sigma),
            "threshold_pct": float(p.threshold_pct),
            "expected_accuracy_pct": float(p.expected_accuracy_pct),
            "match_rate_pct": float(p.match_rate_pct),
        }

    return {
        "up": [pack(p) for p in ups],
        "down": [pack(p) for p in dns],
    }


def window_edge_flag(pair: Pair, *, t0: datetime | None = None, min_sigma: float = 0.25) -> dict[str, Any]:
    """Compute pct_diff from indicators and return a JSON-serializable flag payload."""
    root = Path(__file__).resolve().parents[2]
    db_url = _load_db_url(root / ".env")

    now = datetime.now(timezone.utc)
    t0 = t0 or floor_to_quarter_hour(now)

    pct = compute_pct_diff_from_indicators(db_url, pair, t0)
    payload: dict[str, Any] = {
        "pair": pair,
        "t0_utc": t0.astimezone(timezone.utc).isoformat(),
        "now_utc": now.isoformat(),
        "feature": {
            "name": "pct_diff_pre_to_post",
            "definition": "((close@t0+1m - open@t0-3m) / open@t0-3m) * 100",
            "value": pct,
        },
        "min_sigma": min_sigma,
        "passed_thresholds": None,
        "signal": None,
        "status": None,
    }

    if pct is None:
        payload["status"] = "missing_1m_candles_for_window"
        return payload

    sig = best_signal_from_pct_diff(pair, payload["t0_utc"], pct, min_sigma=min_sigma)
    payload["passed_thresholds"] = passed_thresholds(pair, pct, min_sigma=min_sigma)
    payload["signal"] = dataclasses.asdict(sig)
    payload["status"] = "ok" if sig.prediction is not None else "no_trigger"
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True, choices=["BTC-USD", "ETH-USD"])
    ap.add_argument(
        "--t0",
        help="UTC event start (15m boundary). If omitted, uses current quarter-hour floor. Example: 2026-02-10T20:15:00Z",
    )
    ap.add_argument("--min-sigma", type=float, default=0.25)
    ap.add_argument(
        "--print-thresholds",
        action="store_true",
        help="Print the hard thresholds + expected accuracy/match-rate (from training) and exit.",
    )
    args = ap.parse_args()

    if args.print_thresholds:
        pts = THRESHOLDS[args.pair]
        out = {
            "pair": args.pair,
            "definition": "pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100",
            "up": [dataclasses.asdict(p) for p in pts["up"]],
            "down": [dataclasses.asdict(p) for p in pts["down"]],
        }
        print(json.dumps(out, indent=2, sort_keys=False))
        return

    t0 = None
    if args.t0:
        s = args.t0.strip()
        # Accept common Postgres timestamptz renderings, e.g. "2026-02-10 23:30:00+00".
        s = s.replace("Z", "+00:00")
        if "T" not in s and " " in s:
            s = s.replace(" ", "T", 1)
        # Normalize timezone offsets like +00 / -05 to +00:00 / -05:00
        if len(s) >= 3 and s[-3] in "+-" and s[-2:].isdigit() and ":" not in s[-6:]:
            s = s + ":00"
        t0 = datetime.fromisoformat(s)
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)

    payload = window_edge_flag(args.pair, t0=t0, min_sigma=float(args.min_sigma))
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
