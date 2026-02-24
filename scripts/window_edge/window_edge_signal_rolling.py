#!/usr/bin/env python3
"""Window-edge boundary momentum signal (rolling thresholds).

This is the rolling variant of `window_edge_signal.py`.

At a 15m boundary (t0 at :00/:15/:30/:45), compute:
  pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100

Then compute rolling mean/std of pct_diff over the prior `lookback_days` using only
quarter-hour boundaries for that pair (excluding the current event).

Decision (for sigma ladder k):
- UP trigger if pct_diff > mu + k*sd
- DOWN trigger if pct_diff < mu - k*sd

This script queries `indicators` schema (serving data).
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


SIGMAS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


# Reference accuracies from training-schema rolling-21d evaluation (for context only).
# Source: scripts/output/window_edge_rolling/20260211T000555Z/REPORT.md
REFERENCE_TRAINING_ROLLING_21D: dict[Pair, dict[str, dict[float, float]]] = {
    "BTC-USD": {
        "UP": {
            0.25: 58.3293,
            0.5: 60.3912,
            0.75: 61.9914,
            1.0: 63.5992,
            1.5: 65.9728,
            2.0: 67.9267,
            3.0: 68.6332,
            4.0: 70.0397,
        },
        "DOWN": {
            0.25: 57.2793,
            0.5: 58.8805,
            0.75: 60.2797,
            1.0: 61.9413,
            1.5: 63.7815,
            2.0: 65.0236,
            3.0: 65.6951,
            4.0: 70.0240,
        },
    },
    "ETH-USD": {
        "UP": {
            0.25: 57.0660,
            0.5: 58.8582,
            0.75: 60.6317,
            1.0: 62.5390,
            1.5: 64.9584,
            2.0: 66.1888,
            3.0: 70.1699,
            4.0: 69.9561,
        },
        "DOWN": {
            0.25: 56.6819,
            0.5: 58.1879,
            0.75: 59.3806,
            1.0: 60.2608,
            1.5: 62.4430,
            2.0: 63.6847,
            3.0: 66.3082,
            4.0: 62.9526,
        },
    },
}


@dataclass(frozen=True)
class RollingStats:
    mu: float
    sd: float
    n: int


@dataclass(frozen=True)
class RollingThresholdPoint:
    sigma: float
    threshold_pct: float


@dataclass(frozen=True)
class Signal:
    pair: Pair
    t0_utc: str
    pct_diff: float
    lookback_days: int
    rolling_mu: float
    rolling_sd: float
    rolling_n: int
    prediction: Direction | None
    sigma: float | None
    threshold_pct: float | None
    reference_training_accuracy_pct: float | None


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


def _psql_json(db_url: str, sql: str) -> dict[str, Any]:
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
    if not out:
        return {}
    return json.loads(out)


def floor_to_quarter_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")
    m = (dt.minute // 15) * 15
    return dt.replace(minute=m, second=0, microsecond=0)


def _parse_t0(s: str) -> datetime:
    s = s.strip()
    s = s.replace("Z", "+00:00")
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    if len(s) >= 3 and s[-3] in "+-" and s[-2:].isdigit() and ":" not in s[-6:]:
        s = s + ":00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_pct_diff_and_stats(
    db_url: str,
    pair: Pair,
    t0: datetime,
    *,
    lookback_days: int,
) -> tuple[float | None, RollingStats | None]:
    """Compute current pct_diff and rolling (mu, sd, n) from indicators."""

    t0_iso = t0.astimezone(timezone.utc).isoformat()

    sql = f"""
with
params as (
  select
    '{pair}'::text as pair,
    '{t0_iso}'::timestamptz as t0,
    interval '{lookback_days} days' as lb
),

curr as (
  select
    (
      (
        (select close::float8 from indicators.ohlcv_1m
         where pair=(select pair from params)
           and bucket_time=(select t0 from params) + interval '1 minute'
        )
        -
        (select open::float8 from indicators.ohlcv_1m
         where pair=(select pair from params)
           and bucket_time=(select t0 from params) - interval '3 minutes'
        )
      )
      /
      nullif(
        (select open::float8 from indicators.ohlcv_1m
         where pair=(select pair from params)
           and bucket_time=(select t0 from params) - interval '3 minutes'
        ),
        0.0
      )
    ) * 100.0 as pct_diff
),

hist_t0 as (
  select bucket_time as t0
  from indicators.ohlcv_15m
  where pair=(select pair from params)
    and bucket_time >= (select t0 from params) - (select lb from params)
    and bucket_time <  (select t0 from params)
    and extract(second from bucket_time) = 0
    and extract(minute from bucket_time) in (0,15,30,45)
),

hist as (
  select
    (
      (
        m_post.close::float8 - m_pre.open::float8
      ) / nullif(m_pre.open::float8, 0.0)
    ) * 100.0 as pct_diff
  from hist_t0 h
  join indicators.ohlcv_1m m_pre
    on m_pre.pair=(select pair from params)
   and m_pre.bucket_time = h.t0 - interval '3 minutes'
  join indicators.ohlcv_1m m_post
    on m_post.pair=(select pair from params)
   and m_post.bucket_time = h.t0 + interval '1 minute'
  where m_pre.open is not null and m_post.close is not null
),

stats as (
  select
    avg(pct_diff)::float8 as mu,
    stddev_samp(pct_diff)::float8 as sd,
    count(*)::int as n
  from hist
)

select jsonb_build_object(
  'pct_diff', (select pct_diff from curr),
  'mu', (select mu from stats),
  'sd', (select sd from stats),
  'n', (select n from stats)
)::text;
"""

    obj = _psql_json(db_url, sql)
    if not obj:
        return None, None

    pct = obj.get("pct_diff")
    mu = obj.get("mu")
    sd = obj.get("sd")
    n = obj.get("n")

    pct_val = None if pct is None else float(pct)
    stats_val = None
    if mu is not None and sd is not None and n is not None:
        stats_val = RollingStats(mu=float(mu), sd=float(sd), n=int(n))
    return pct_val, stats_val


def _passed_thresholds(pct: float, mu: float, sd: float, *, min_sigma: float) -> dict[str, list[RollingThresholdPoint]]:
    ups = []
    dns = []
    for k in SIGMAS:
        if k < min_sigma:
            continue
        if pct > mu + k * sd:
            ups.append(RollingThresholdPoint(sigma=k, threshold_pct=mu + k * sd))
        if pct < mu - k * sd:
            dns.append(RollingThresholdPoint(sigma=k, threshold_pct=mu - k * sd))
    ups.sort(key=lambda p: p.sigma, reverse=True)
    dns.sort(key=lambda p: p.sigma, reverse=True)
    return {"up": ups, "down": dns}


def rolling_window_edge_flag(
    pair: Pair,
    *,
    t0: datetime | None = None,
    min_sigma: float = 0.25,
    lookback_days: int = 21,
    min_n: int = 500,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    db_url = _load_db_url(root / ".env")

    now = datetime.now(timezone.utc)
    t0 = t0 or floor_to_quarter_hour(now)

    pct, st = compute_pct_diff_and_stats(db_url, pair, t0, lookback_days=lookback_days)

    payload: dict[str, Any] = {
        "pair": pair,
        "t0_utc": t0.astimezone(timezone.utc).isoformat(),
        "now_utc": now.isoformat(),
        "lookback_days": lookback_days,
        "min_sigma": float(min_sigma),
        "min_n": int(min_n),
        "feature": {
            "name": "pct_diff_pre_to_post",
            "definition": "((close@t0+1m - open@t0-3m) / open@t0-3m) * 100",
            "value": pct,
        },
        "rolling": None,
        "passed_thresholds": None,
        "signal": None,
        "status": None,
    }

    if pct is None or st is None:
        payload["status"] = "missing_data"
        return payload

    payload["rolling"] = {"mu": st.mu, "sd": st.sd, "n": st.n}

    if st.n < min_n or st.sd <= 0:
        payload["status"] = "insufficient_history"
        return payload

    passed = _passed_thresholds(pct, st.mu, st.sd, min_sigma=min_sigma)
    payload["passed_thresholds"] = {
        "up": [dataclasses.asdict(p) for p in passed["up"]],
        "down": [dataclasses.asdict(p) for p in passed["down"]],
    }

    pred: Direction | None = None
    chosen_sigma: float | None = None
    chosen_thr: float | None = None

    # Strongest threshold wins.
    if passed["up"]:
        pred = "UP"
        chosen_sigma = passed["up"][0].sigma
        chosen_thr = passed["up"][0].threshold_pct
    elif passed["down"]:
        pred = "DOWN"
        chosen_sigma = passed["down"][0].sigma
        chosen_thr = passed["down"][0].threshold_pct

    ref_acc = None
    if pred is not None and chosen_sigma is not None:
        ref_acc = REFERENCE_TRAINING_ROLLING_21D.get(pair, {}).get(pred, {}).get(float(chosen_sigma))

    sig = Signal(
        pair=pair,
        t0_utc=payload["t0_utc"],
        pct_diff=float(pct),
        lookback_days=lookback_days,
        rolling_mu=st.mu,
        rolling_sd=st.sd,
        rolling_n=st.n,
        prediction=pred,
        sigma=chosen_sigma,
        threshold_pct=chosen_thr,
        reference_training_accuracy_pct=ref_acc,
    )

    payload["signal"] = dataclasses.asdict(sig)
    payload["status"] = "ok" if pred is not None else "no_trigger"
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True, choices=["BTC-USD", "ETH-USD"])
    ap.add_argument(
        "--t0",
        help="UTC event start (15m boundary). If omitted, uses current quarter-hour floor. Example: 2026-02-10T20:15:00Z",
    )
    ap.add_argument("--min-sigma", type=float, default=0.25)
    ap.add_argument("--lookback-days", type=int, default=21)
    ap.add_argument("--min-n", type=int, default=500)
    ap.add_argument(
        "--print-thresholds",
        action="store_true",
        help="Compute and print the rolling thresholds for this t0 (mu±k*sd) and exit.",
    )
    args = ap.parse_args()

    t0 = _parse_t0(args.t0) if args.t0 else None

    payload = rolling_window_edge_flag(
        args.pair,
        t0=t0,
        min_sigma=float(args.min_sigma),
        lookback_days=int(args.lookback_days),
        min_n=int(args.min_n),
    )

    if args.print_thresholds and payload.get("rolling"):
        mu = float(payload["rolling"]["mu"])
        sd = float(payload["rolling"]["sd"])
        thr = {
            "pair": args.pair,
            "t0_utc": payload["t0_utc"],
            "lookback_days": int(args.lookback_days),
            "rolling": payload["rolling"],
            "thresholds": {
                "up": [{"sigma": k, "threshold_pct": mu + k * sd} for k in SIGMAS if k >= float(args.min_sigma)],
                "down": [{"sigma": k, "threshold_pct": mu - k * sd} for k in SIGMAS if k >= float(args.min_sigma)],
            },
        }
        print(json.dumps(thr, indent=2, sort_keys=False))
        return

    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
