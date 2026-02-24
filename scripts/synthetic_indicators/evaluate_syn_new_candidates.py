#!/usr/bin/env python3
"""Evaluate proposed synthetic indicators from syn_new.txt without deploying them.

For each candidate indicator:
1) Compute feature value per 15m event bucket (t0 in :00/:15/:30/:45).
2) Score native decision logic from the proposal.
3) Run threshold-correlation sweep (best >= / <= rules) like prior synthetic analysis.

Range defaults to 2026-01-22 -> now (latest fully closed 15m event).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


START_DEFAULT = "2026-01-22T00:00:00Z"


def load_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def psql_csv(db_url: str, sql: str) -> list[dict[str, str]]:
    out = subprocess.check_output(
        [
            "psql",
            db_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-A",
            "-F",
            ",",
            "--csv",
            "-c",
            sql,
        ],
        text=True,
    )
    return list(csv.DictReader(out.splitlines()))


def _end_expr(end_ts: str) -> str:
    if end_ts.lower() == "now":
        # last fully closed 15m event start
        return "(date_trunc('minute', now()) - interval '15 minutes')"
    return f"'{end_ts}'::timestamptz"


def _base_events_cte(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    pair_sql = ", ".join(f"'{p}'" for p in pairs)
    end_expr = _end_expr(end_ts)
    return f"""
with base_events as (
  select
    o15.pair,
    o15.bucket_time as t0,
    o15.open::float8 as open_15m,
    o15.close::float8 as close_15m,
    case
      when o14.close > o0.open then 'up'
      when o14.close < o0.open then 'down'
      else null
    end as outcome
  from indicators.ohlcv_15m o15
  join indicators.ohlcv_1m o0
    on o0.pair = o15.pair and o0.bucket_time = o15.bucket_time
  join indicators.ohlcv_1m o14
    on o14.pair = o15.pair and o14.bucket_time = o15.bucket_time + interval '14 minutes'
  where o15.pair in ({pair_sql})
    and o15.bucket_time >= '{start_ts}'::timestamptz
    and o15.bucket_time <= {_end_expr(end_ts)}
    and extract(minute from o15.bucket_time)::int in (0,15,30,45)
)
"""


def query_rsi_vol_norm_velocity(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    base = _base_events_cte(start_ts, end_ts, pairs)
    return f"""
{base},
raw as (
  select
    e.pair,
    e.t0,
    e.outcome,
    r0.v1::float8 as rsi_t0,
    r3.v1::float8 as rsi_t3,
    a15.v1::float8 as atr_15m,
    c0.close::float8 as close_t0,
    c1.close::float8 as close_t1
  from base_events e
  left join indicators.indicator_values r0
    on r0.pair = e.pair and r0.bucket_time = e.t0 and r0.config_id = 'rsi_14_15m'
  left join indicators.indicator_values r3
    on r3.pair = e.pair and r3.bucket_time = e.t0 - interval '45 minutes' and r3.config_id = 'rsi_14_15m'
  left join indicators.indicator_values a15
    on a15.pair = e.pair and a15.bucket_time = e.t0 and a15.config_id = 'atr_14_15m'
  left join indicators.ohlcv_1m c0
    on c0.pair = e.pair and c0.bucket_time = e.t0
  left join indicators.ohlcv_1m c1
    on c1.pair = e.pair and c1.bucket_time = e.t0 + interval '1 minute'
  where e.outcome in ('up','down')
),
val as (
  select
    pair, t0, outcome, rsi_t0,
    ((((rsi_t0 - rsi_t3) / 3.0) / ((atr_15m / (close_t0 + 1e-9)) + 1e-9)) * sign(close_t1 - close_t0))::float8 as value
  from raw
),
scored as (
  select
    *,
    stddev_samp(value) over (partition by pair) as sigma
  from val
  where value is not null
)
select
  'rsi_volatility_normalized_velocity'::text as candidate,
  pair,
  t0,
  outcome,
  value,
  case
    when sigma > 0 and value < -1.0 * sigma and rsi_t0 > 35 then 'down'
    when sigma > 0 and value >  1.0 * sigma and rsi_t0 < 65 then 'up'
    else null
  end as prediction_native
from scored
order by pair, t0
"""


def query_cvd_price_divergence_velocity(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    base = _base_events_cte(start_ts, end_ts, pairs)
    return f"""
{base},
raw as (
  select
    e.pair,
    e.t0,
    e.outcome,
    cv0.v1::float8 as cvd_t0,
    cv5.v1::float8 as cvd_t5,
    e.close_15m::float8 as close_t0,
    c5.close::float8 as close_t5,
    a15.v1::float8 as atr_15m
  from base_events e
  left join indicators.indicator_values cv0
    on cv0.pair = e.pair and cv0.bucket_time = e.t0 and cv0.config_id = 'cvd_50_15m'
  left join indicators.indicator_values cv5
    on cv5.pair = e.pair and cv5.bucket_time = e.t0 - interval '75 minutes' and cv5.config_id = 'cvd_50_15m'
  left join indicators.ohlcv_15m c5
    on c5.pair = e.pair and c5.bucket_time = e.t0 - interval '75 minutes'
  left join indicators.indicator_values a15
    on a15.pair = e.pair and a15.bucket_time = e.t0 and a15.config_id = 'atr_14_15m'
  where e.outcome in ('up','down')
),
roll as (
  select
    *,
    stddev_samp(cvd_t0) over (
      partition by pair
      order by t0
      rows between 19 preceding and current row
    ) as cvd_sd20
  from raw
),
val as (
  select
    pair,
    t0,
    outcome,
    close_t0,
    close_t5,
    (
      ((cvd_t0 - cvd_t5) / (coalesce(cvd_sd20, 0.0) + 1e-9))
      -
      ((close_t0 - close_t5) / ((atr_15m * sqrt(5.0)) + 1e-9))
    )::float8 as value
  from roll
  where cvd_t0 is not null and cvd_t5 is not null and close_t0 is not null and close_t5 is not null and atr_15m is not null
),
scored as (
  select
    *,
    stddev_samp(value) over (partition by pair) as sigma
  from val
  where value is not null
)
select
  'cvd_price_divergence_velocity'::text as candidate,
  pair,
  t0,
  outcome,
  value,
  case
    when sigma > 0 and value < -1.2 * sigma and close_t0 > close_t5 then 'down'
    when sigma > 0 and value >  1.2 * sigma and close_t0 < close_t5 then 'up'
    else null
  end as prediction_native
from scored
order by pair, t0
"""


def query_atr_normalized_reversal_pressure(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    base = _base_events_cte(start_ts, end_ts, pairs)
    return f"""
{base},
raw as (
  select
    e.pair,
    e.t0,
    e.outcome,
    e.open_15m,
    c1.close::float8 as close_t1m,
    c5_0.close::float8 as close_5m_t0,
    c5_15.close::float8 as close_5m_t15,
    a5.v1::float8 as atr_14_5m,
    m0.v3::float8 as macd_hist_t0,
    m1.v3::float8 as macd_hist_t1,
    m2.v3::float8 as macd_hist_t2
  from base_events e
  left join indicators.ohlcv_1m c1
    on c1.pair = e.pair and c1.bucket_time = e.t0 + interval '1 minute'
  left join indicators.ohlcv_5m c5_0
    on c5_0.pair = e.pair and c5_0.bucket_time = e.t0
  left join indicators.ohlcv_5m c5_15
    on c5_15.pair = e.pair and c5_15.bucket_time = e.t0 - interval '15 minutes'
  left join indicators.indicator_values a5
    on a5.pair = e.pair and a5.bucket_time = e.t0 and a5.config_id = 'atr_14_5m'
  left join indicators.indicator_values m0
    on m0.pair = e.pair and m0.bucket_time = e.t0 and m0.config_id = 'macd_12_26_9_5m'
  left join indicators.indicator_values m1
    on m1.pair = e.pair and m1.bucket_time = e.t0 - interval '5 minutes' and m1.config_id = 'macd_12_26_9_5m'
  left join indicators.indicator_values m2
    on m2.pair = e.pair and m2.bucket_time = e.t0 - interval '10 minutes' and m2.config_id = 'macd_12_26_9_5m'
  where e.outcome in ('up','down')
),
val as (
  select
    pair,
    t0,
    outcome,
    open_15m,
    close_t1m,
    atr_14_5m,
    ((close_5m_t0 - close_5m_t15) / nullif(atr_14_5m, 0.0))::float8 as price_extension,
    (macd_hist_t1 > macd_hist_t2 and macd_hist_t1 > macd_hist_t0) as is_hist_peak
  from raw
  where close_5m_t0 is not null and close_5m_t15 is not null and atr_14_5m is not null
),
scored as (
  select
    *,
    (
      abs(price_extension)
      * (case when is_hist_peak then 1.0 else 0.4 end)
      * (
          case
            when (price_extension > 0 and close_t1m < open_15m)
              or (price_extension < 0 and close_t1m > open_15m) then 1.5
            else 0.7
          end
        )
    )::float8 as value
  from val
)
select
  'atr_normalized_reversal_pressure'::text as candidate,
  pair,
  t0,
  outcome,
  value,
  case
    when price_extension > 1.8
      and is_hist_peak
      and close_t1m < (open_15m - 0.3 * atr_14_5m) then 'down'
    when price_extension < -1.8
      and is_hist_peak
      and close_t1m > (open_15m + 0.3 * atr_14_5m) then 'up'
    else null
  end as prediction_native
from scored
where value is not null
order by pair, t0
"""


def query_multitimeframe_trend_confluence(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    base = _base_events_cte(start_ts, end_ts, pairs)
    return f"""
{base},
raw as (
  select
    e.pair,
    e.t0,
    e.outcome,
    e.close_15m::float8 as close_15m_t0,
    st5.v1::float8 as st_5m,
    st15.v1::float8 as st_15m,
    ema9_0.v1::float8 as ema9_t0,
    ema9_1.v1::float8 as ema9_t1,
    ema21_0.v1::float8 as ema21_t0,
    ema21_1.v1::float8 as ema21_t1,
    c5.close::float8 as close_5m_t0,
    c5.high::float8 as high_5m_t0,
    c5.low::float8 as low_5m_t0,
    c1.close::float8 as close_1m_t1
  from base_events e
  left join indicators.indicator_values st5
    on st5.pair = e.pair and st5.bucket_time = e.t0 and st5.config_id = 'supertrend_10_3_5m'
  left join indicators.indicator_values st15
    on st15.pair = e.pair and st15.bucket_time = e.t0 and st15.config_id = 'supertrend_10_3_15m'
  left join indicators.indicator_values ema9_0
    on ema9_0.pair = e.pair and ema9_0.bucket_time = e.t0 and ema9_0.config_id = 'ema_9_15m'
  left join indicators.indicator_values ema9_1
    on ema9_1.pair = e.pair and ema9_1.bucket_time = e.t0 - interval '15 minutes' and ema9_1.config_id = 'ema_9_15m'
  left join indicators.indicator_values ema21_0
    on ema21_0.pair = e.pair and ema21_0.bucket_time = e.t0 and ema21_0.config_id = 'ema_21_15m'
  left join indicators.indicator_values ema21_1
    on ema21_1.pair = e.pair and ema21_1.bucket_time = e.t0 - interval '15 minutes' and ema21_1.config_id = 'ema_21_15m'
  left join indicators.ohlcv_5m c5
    on c5.pair = e.pair and c5.bucket_time = e.t0
  left join indicators.ohlcv_1m c1
    on c1.pair = e.pair and c1.bucket_time = e.t0 + interval '1 minute'
  where e.outcome in ('up','down')
),
scored as (
  select
    *,
    (case when st_5m < close_5m_t0 then 1.0 else -1.0 end) as st_5m_dir,
    (case when st_15m < close_15m_t0 then 1.0 else -1.0 end) as st_15m_dir,
    (case when ((ema9_t0 - ema9_t1) - (ema21_t0 - ema21_t1)) > 0 then 1.0 else -1.0 end) as ema_dir,
    (high_5m_t0 - low_5m_t0) as atr_5m_simple
  from raw
  where st_5m is not null and st_15m is not null
    and ema9_t0 is not null and ema9_t1 is not null
    and ema21_t0 is not null and ema21_t1 is not null
    and close_5m_t0 is not null and high_5m_t0 is not null and low_5m_t0 is not null
),
val as (
  select
    *,
    (
      (st_5m_dir + st_15m_dir + ema_dir)
      * (case when atr_5m_simple > 0.0012 * close_5m_t0 then 1.0 else 0.2 end)
    )::float8 as value
  from scored
)
select
  'multitimeframe_trend_confluence'::text as candidate,
  pair,
  t0,
  outcome,
  value,
  case
    when value <= -2.0 and close_1m_t1 < ema9_t0 then 'down'
    when value >=  2.0 and close_1m_t1 > ema9_t0 then 'up'
    else null
  end as prediction_native
from val
where value is not null
order by pair, t0
"""


CANDIDATES = [
    ("rsi_volatility_normalized_velocity", query_rsi_vol_norm_velocity),
    ("cvd_price_divergence_velocity", query_cvd_price_divergence_velocity),
    ("atr_normalized_reversal_pressure", query_atr_normalized_reversal_pressure),
    ("multitimeframe_trend_confluence", query_multitimeframe_trend_confluence),
]


@dataclass(frozen=True)
class RuleResult:
    side: str
    operator: str
    threshold: float
    support_n: int
    support_pct: float
    wins: int
    precision: float
    lift_vs_base: float


def _best_rule_for_side(
    side: str,
    x: np.ndarray,
    y_is_up: np.ndarray,
    min_count: int,
) -> RuleResult | None:
    n = x.size
    if n == 0:
        return None
    y_side = y_is_up if side == "up" else ~y_is_up
    base_rate = float(np.mean(y_side))

    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ys = y_side[order].astype(np.int64)

    uniq, first_idx, counts = np.unique(xs, return_index=True, return_counts=True)
    last_idx = first_idx + counts - 1
    prefix = np.cumsum(ys)
    total = int(prefix[-1])

    best: RuleResult | None = None

    n_le = last_idx + 1
    wins_le = prefix[last_idx]
    for i, t in enumerate(uniq):
        cnt = int(n_le[i])
        if cnt < min_count:
            continue
        wins = int(wins_le[i])
        prec = wins / cnt if cnt else 0.0
        cand = RuleResult(side, "<=", float(t), cnt, cnt / n, wins, prec, prec - base_rate)
        if (best is None) or (cand.precision > best.precision) or (
            np.isclose(cand.precision, best.precision) and cand.support_n > best.support_n
        ):
            best = cand

    wins_before_first = np.where(first_idx > 0, prefix[first_idx - 1], 0)
    n_ge = n - first_idx
    wins_ge = total - wins_before_first
    for i, t in enumerate(uniq):
        cnt = int(n_ge[i])
        if cnt < min_count:
            continue
        wins = int(wins_ge[i])
        prec = wins / cnt if cnt else 0.0
        cand = RuleResult(side, ">=", float(t), cnt, cnt / n, wins, prec, prec - base_rate)
        if (best is None) or (cand.precision > best.precision) or (
            np.isclose(cand.precision, best.precision) and cand.support_n > best.support_n
        ):
            best = cand

    return best


def native_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    n_total = len(rows)
    triggered = [r for r in rows if r.get("prediction_native") in ("up", "down")]
    n_trig = len(triggered)
    n_up = sum(1 for r in triggered if r["prediction_native"] == "up")
    n_dn = sum(1 for r in triggered if r["prediction_native"] == "down")
    up_wins = sum(1 for r in triggered if r["prediction_native"] == "up" and r["outcome"] == "up")
    dn_wins = sum(1 for r in triggered if r["prediction_native"] == "down" and r["outcome"] == "down")
    wins = up_wins + dn_wins
    losses = n_trig - wins
    return {
        "n_total": n_total,
        "n_triggered": n_trig,
        "coverage_pct": (n_trig / n_total) if n_total else 0.0,
        "wins": wins,
        "losses": losses,
        "accuracy_pct": (wins / n_trig) if n_trig else None,
        "n_pred_up": n_up,
        "n_pred_down": n_dn,
        "up_accuracy_pct": (up_wins / n_up) if n_up else None,
        "down_accuracy_pct": (dn_wins / n_dn) if n_dn else None,
    }


def evaluate_threshold_group(task: tuple[str, str, list[dict[str, str]], float, int]) -> dict[str, Any]:
    candidate, pair, rows, min_support_pct, min_support_n = task
    x = np.array([float(r["value"]) for r in rows], dtype=np.float64)
    y_up = np.array([r["outcome"] == "up" for r in rows], dtype=bool)
    n = x.size
    min_count = max(min_support_n, int(math.ceil(n * min_support_pct)))
    base_up = float(np.mean(y_up)) if n else 0.0
    base_down = 1.0 - base_up
    bu = _best_rule_for_side("up", x, y_up, min_count) if n else None
    bd = _best_rule_for_side("down", x, y_up, min_count) if n else None

    def as_dict(rr: RuleResult | None) -> dict[str, Any] | None:
        if rr is None:
            return None
        return {
            "side": rr.side,
            "operator": rr.operator,
            "threshold": rr.threshold,
            "support_n": rr.support_n,
            "support_pct": rr.support_pct,
            "wins": rr.wins,
            "precision": rr.precision,
            "lift_vs_base": rr.lift_vs_base,
        }

    return {
        "candidate": candidate,
        "pair": pair,
        "n_total": int(n),
        "min_support_n_used": int(min_count),
        "base_up_rate": base_up,
        "base_down_rate": base_down,
        "best_up_rule": as_dict(bu),
        "best_down_rule": as_dict(bd),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Evaluate syn_new candidate indicators.")
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--end", default="now")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD")
    ap.add_argument("--min-support-pct", type=float, default=0.05)
    ap.add_argument("--min-support-n", type=int, default=30)
    ap.add_argument("--query-workers", type=int, default=4)
    ap.add_argument("--analysis-workers", type=int, default=max(2, (os.cpu_count() or 8) - 1))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    queries = [
        (name, builder(args.start, args.end, pairs))
        for name, builder in CANDIDATES
    ]

    def run_query(item: tuple[str, str]) -> tuple[str, list[dict[str, str]]]:
        nm, q = item
        return nm, psql_csv(db_url, q)

    with ThreadPoolExecutor(max_workers=max(1, args.query_workers)) as ex:
        raw_blocks = dict(ex.map(run_query, queries))

    by_candidate_pair: dict[tuple[str, str], list[dict[str, str]]] = {}
    for cand, rows in raw_blocks.items():
        for r in rows:
            by_candidate_pair.setdefault((cand, r["pair"]), []).append(r)

    native_summary: list[dict[str, Any]] = []
    for (cand, pair), rows in sorted(by_candidate_pair.items()):
        native = native_metrics(rows)
        native_summary.append({"candidate": cand, "pair": pair, **native})

    threshold_tasks = [
        (cand, pair, rows, args.min_support_pct, args.min_support_n)
        for (cand, pair), rows in sorted(by_candidate_pair.items())
    ]
    with ProcessPoolExecutor(max_workers=max(1, args.analysis_workers)) as ex:
        threshold_summary = list(ex.map(evaluate_threshold_group, threshold_tasks))

    threshold_summary.sort(key=lambda x: (x["candidate"], x["pair"]))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "syn_new_eval" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": args.start,
        "end": args.end,
        "pairs": pairs,
        "min_support_pct": args.min_support_pct,
        "min_support_n": args.min_support_n,
        "native_summary": native_summary,
        "threshold_summary": threshold_summary,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))

    # write detailed rows
    for cand, rows in raw_blocks.items():
        out_csv = out_dir / f"rows_{cand}.csv"
        if rows:
            fields = list(rows[0].keys())
            with out_csv.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)

    lines: list[str] = []
    lines.append("# Candidate Synthetic Evaluation (syn_new)")
    lines.append("")
    lines.append(f"Range: `{args.start}` -> `{args.end}`")
    lines.append(f"Pairs: `{','.join(pairs)}`")
    lines.append(
        f"Threshold sweep support floor: `max({args.min_support_n}, {args.min_support_pct:.2%} of group)`"
    )
    lines.append("")
    lines.append("## Native Decision Logic Results")
    lines.append("")
    lines.append(
        "candidate | pair | n_total | triggered | coverage | accuracy | up_acc | down_acc"
    )
    lines.append("---|---:|---:|---:|---:|---:|---:|---:")
    for r in native_summary:
        acc = "" if r["accuracy_pct"] is None else f"{r['accuracy_pct']*100:.2f}%"
        up_acc = "" if r["up_accuracy_pct"] is None else f"{r['up_accuracy_pct']*100:.2f}%"
        dn_acc = "" if r["down_accuracy_pct"] is None else f"{r['down_accuracy_pct']*100:.2f}%"
        lines.append(
            f"{r['candidate']} | {r['pair']} | {r['n_total']} | {r['n_triggered']} | "
            f"{(r['coverage_pct']*100):.2f}% | "
            f"{acc} | {up_acc} | {dn_acc}"
        )

    lines.append("")
    lines.append("## Best Threshold Correlation (Same Method Used On Prior Synthetics)")
    lines.append("")
    for r in threshold_summary:
        lines.append(f"### {r['candidate']} / {r['pair']}")
        lines.append(
            f"- n_total: **{r['n_total']}**, base up/down: **{r['base_up_rate']*100:.2f}% / {r['base_down_rate']*100:.2f}%**"
        )
        bu = r.get("best_up_rule")
        bd = r.get("best_down_rule")
        if bu:
            lines.append(
                f"- best UP rule: `value {bu['operator']} {bu['threshold']:.6f}` -> "
                f"UP **{bu['precision']*100:.2f}%** (support {bu['support_n']} / {bu['support_pct']*100:.2f}%)"
            )
        if bd:
            lines.append(
                f"- best DOWN rule: `value {bd['operator']} {bd['threshold']:.6f}` -> "
                f"DOWN **{bd['precision']*100:.2f}%** (support {bd['support_n']} / {bd['support_pct']*100:.2f}%)"
            )
        lines.append("")

    (out_dir / "REPORT.md").write_text("\n".join(lines).rstrip() + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
