#!/usr/bin/env python3
"""Compare non-rolling vs rolling window-edge signals over last 48 hours (BTC only).

- Non-rolling: uses frozen hard thresholds from training discovery.
- Rolling: uses dynamic mu/sd computed from prior 21 days at each event.

Events:
- 15m boundaries (t0 minute in {0,15,30,45}), last 48 hours window.
- We assume decision time at :02/:17/:32/:47 (t0+2m), which includes the needed t0+1m close.

Outputs:
- scripts/output/window_edge_compare/<UTC>/REPORT.md
- scripts/output/window_edge_compare/<UTC>/events.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PAIR = "BTC-USD"

# Hard thresholds (BTC-USD) from scripts/window_edge/window_edge_signal.py
# Condition:
# - UP: pct_diff > threshold
# - DOWN: pct_diff < threshold (negative)
UP_THRESHOLDS = [
    (4.0, 0.8684955454034570),
    (3.0, 0.6522135931454520),
    (2.0, 0.4359316408874480),
    (1.5, 0.3277906647584450),
    (1.0, 0.2196496886294430),
    (0.75, 0.1655792005649420),
    (0.5, 0.1115087125004410),
    (0.25, 0.0574382244359396),
]
DOWN_THRESHOLDS = [
    (4.0, -0.8617600726605840),
    (3.0, -0.6454781204025780),
    (2.0, -0.4291961681445730),
    (1.5, -0.3210551920155700),
    (1.0, -0.2129142158865670),
    (0.75, -0.1588437278220660),
    (0.5, -0.1047732397575640),
    (0.25, -0.0507027516930629),
]


def load_db_url(root: Path) -> str:
    env_path = root / ".env"
    env = {}
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


def psql_copy(db_url: str, sql: str, out_csv: Path) -> None:
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
        "-c",
        f"\\copy ({sql}) TO STDOUT WITH CSV HEADER",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        subprocess.check_call(cmd, stdout=f)


@dataclass
class Event:
    t0: str
    pct_diff: float
    outcome_up: int
    mu: float
    sd: float
    n: int


def nonrolling_pred(pct_diff: float, min_sigma: float) -> tuple[int | None, float | None]:
    # returns (pred, sigma)
    for sigma, thr in UP_THRESHOLDS:
        if sigma >= min_sigma and pct_diff > thr:
            return 1, sigma
    for sigma, thr in DOWN_THRESHOLDS:
        if sigma >= min_sigma and pct_diff < thr:
            return 0, sigma
    return None, None


def rolling_pred(pct_diff: float, mu: float, sd: float, n: int, *, lookback_min_n: int, min_sigma: float) -> tuple[int | None, float | None]:
    if n < lookback_min_n or sd <= 0:
        return None, None
    # check strongest first
    for sigma in [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25]:
        if sigma < min_sigma:
            continue
        if pct_diff > mu + sigma * sd:
            return 1, sigma
        if pct_diff < mu - sigma * sd:
            return 0, sigma
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sigma", type=float, default=0.25)
    ap.add_argument("--lookback-days", type=int, default=21)
    ap.add_argument("--lookback-min-n", type=int, default=500)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "window_edge_compare" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine last fully-closed 15m event start (needs t0+15m to be in the past)
    # Use DB now() to avoid local clock skew.
    sql = f"""
with bounds as (
  select
    date_trunc('minute', now()) - interval '15 minutes' as end_t0,
    date_trunc('minute', now()) - interval '15 minutes' - interval '48 hours' as start_exclusive
)
select jsonb_build_object(
  'end_t0', (select end_t0 from bounds),
  'start_exclusive', (select start_exclusive from bounds)
)::text;
"""
    bounds = json.loads(
        subprocess.check_output(
            [
                "psql",
                db_url,
                "-v",
                "ON_ERROR_STOP=1",
                "-P",
                "pager=off",
                "-t",
                "-A",
                "-c",
                sql.strip().rstrip(";"),
            ],
            text=True,
        ).strip()
    )

    end_t0 = bounds["end_t0"]
    start_exclusive = bounds["start_exclusive"]

    # Pull pct_diff + outcome + rolling mu/sd/n for each event in the window.
    # Rolling stats are computed using prior lookback_days of events (excluding current).
    q = f"""
with
window_bounds as (
  select
    '{start_exclusive}'::timestamptz as start_exclusive,
    '{end_t0}'::timestamptz as end_t0,
    interval '{int(args.lookback_days)} days' as lb
),

all_events as (
  select
    o.bucket_time as t0,
    o.open::float8 as open_15m,
    o.close::float8 as close_15m,
    case
      when o.close > o.open then 1
      when o.close < o.open then 0
      else null
    end as outcome_up
  from indicators.ohlcv_15m o
  where o.pair = '{PAIR}'
    and extract(second from o.bucket_time) = 0
    and extract(minute from o.bucket_time) in (0,15,30,45)
    and o.bucket_time >= (select start_exclusive from window_bounds) - (select lb from window_bounds)
    and o.bucket_time <= (select end_t0 from window_bounds)
),

feature as (
  select
    e.t0,
    e.outcome_up,
    (
      (m_post.close::float8 - m_pre.open::float8) / nullif(m_pre.open::float8, 0.0)
    ) * 100.0 as pct_diff
  from all_events e
  join indicators.ohlcv_1m m_pre
    on m_pre.pair = '{PAIR}'
   and m_pre.bucket_time = e.t0 - interval '3 minutes'
  join indicators.ohlcv_1m m_post
    on m_post.pair = '{PAIR}'
   and m_post.bucket_time = e.t0 + interval '1 minute'
  where e.outcome_up is not null
),

roll as (
  select
    f.*,
    avg(pct_diff) over w as mu,
    stddev_samp(pct_diff) over w as sd,
    count(*) over w as n
  from feature f
  window w as (
    order by t0
    range between interval '{int(args.lookback_days)} days' preceding and interval '1 microsecond' preceding
  )
),

final as (
  select *
  from roll
  where t0 > (select start_exclusive from window_bounds)
    and t0 <= (select end_t0 from window_bounds)
)

select
  t0,
  pct_diff,
  outcome_up,
  mu,
  sd,
  n
from final
order by t0;
"""

    events_csv = out_dir / "events.csv"
    psql_copy(db_url, q, events_csv)

    events: list[Event] = []
    with events_csv.open() as f:
        r = csv.DictReader(f)
        for d in r:
            events.append(
                Event(
                    t0=d["t0"],
                    pct_diff=float(d["pct_diff"]),
                    outcome_up=int(d["outcome_up"]),
                    mu=float(d["mu"]) if d["mu"] else float("nan"),
                    sd=float(d["sd"]) if d["sd"] else float("nan"),
                    n=int(d["n"]) if d["n"] else 0,
                )
            )

    total = len(events)

    # Score
    nr_pred = {}
    r_pred = {}

    for ev in events:
        p, s = nonrolling_pred(ev.pct_diff, float(args.min_sigma))
        nr_pred[ev.t0] = (p, s)
        pr, sr = rolling_pred(
            ev.pct_diff,
            ev.mu,
            ev.sd,
            ev.n,
            lookback_min_n=int(args.lookback_min_n),
            min_sigma=float(args.min_sigma),
        )
        r_pred[ev.t0] = (pr, sr)

    def winloss(pred: int | None, y: int) -> tuple[int, int]:
        if pred is None:
            return 0, 0
        return (1, 0) if pred == y else (0, 1)

    def summarize(pred_map):
        n_trig = 0
        wins = 0
        losses = 0
        for ev in events:
            pred, _sigma = pred_map[ev.t0]
            if pred is None:
                continue
            n_trig += 1
            w, l = winloss(pred, ev.outcome_up)
            wins += w
            losses += l
        return n_trig, wins, losses

    nr_n, nr_w, nr_l = summarize(nr_pred)
    r_n, r_w, r_l = summarize(r_pred)

    # Overlap breakdown
    both = []
    only_nr = []
    only_r = []
    neither = []

    for ev in events:
        a = nr_pred[ev.t0][0] is not None
        b = r_pred[ev.t0][0] is not None
        if a and b:
            both.append(ev)
        elif a:
            only_nr.append(ev)
        elif b:
            only_r.append(ev)
        else:
            neither.append(ev)

    def summarize_subset(subset, pred_map):
        n = 0
        w = 0
        l = 0
        for ev in subset:
            pred, _ = pred_map[ev.t0]
            if pred is None:
                continue
            n += 1
            ww, ll = winloss(pred, ev.outcome_up)
            w += ww
            l += ll
        return n, w, l

    both_nr = summarize_subset(both, nr_pred)
    both_r = summarize_subset(both, r_pred)
    only_nr_nr = summarize_subset(only_nr, nr_pred)
    only_r_r = summarize_subset(only_r, r_pred)

    def rate(w, l):
        return w / (w + l) if (w + l) else float("nan")

    report = []
    report.append("# BTC Window-Edge: Non-Rolling vs Rolling (Last 48 Hours)")
    report.append("")
    report.append(f"Run: `{out_dir}`")
    report.append("")
    report.append(f"pair: `{PAIR}`")
    report.append(f"window: (t0 > {start_exclusive}) and (t0 <= {end_t0})")
    report.append(f"expected_events: `192` (48h * 4 per hour)")
    report.append(f"actual_events_scored: `{total}` (excludes flats and requires 1m pre/post candles)")
    report.append("")
    report.append(f"non_rolling: min_sigma={args.min_sigma}")
    report.append(f"rolling: lookback_days={args.lookback_days}, lookback_min_n={args.lookback_min_n}, min_sigma={args.min_sigma}")
    report.append("")
    report.append("## Summary")
    report.append("")
    report.append(f"non_rolling_triggered: {nr_n} | wins: {nr_w} | losses: {nr_l} | win_rate: {rate(nr_w, nr_l):.6f}")
    report.append(f"rolling_triggered:     {r_n} | wins: {r_w} | losses: {r_l} | win_rate: {rate(r_w, r_l):.6f}")
    report.append("")
    report.append("## Overlap")
    report.append("")
    report.append(f"both_triggered: {len(both)}")
    report.append(f"only_non_rolling_triggered: {len(only_nr)}")
    report.append(f"only_rolling_triggered: {len(only_r)}")
    report.append(f"neither_triggered: {len(neither)}")
    report.append("")
    report.append("### Accuracy On Overlap Subsets")
    report.append("")
    report.append(
        f"both_triggered (non_rolling): n={both_nr[0]} wins={both_nr[1]} losses={both_nr[2]} win_rate={rate(both_nr[1], both_nr[2]):.6f}"
    )
    report.append(
        f"both_triggered (rolling):     n={both_r[0]} wins={both_r[1]} losses={both_r[2]} win_rate={rate(both_r[1], both_r[2]):.6f}"
    )
    report.append(
        f"only_non_rolling_triggered:   n={only_nr_nr[0]} wins={only_nr_nr[1]} losses={only_nr_nr[2]} win_rate={rate(only_nr_nr[1], only_nr_nr[2]):.6f}"
    )
    report.append(
        f"only_rolling_triggered:       n={only_r_r[0]} wins={only_r_r[1]} losses={only_r_r[2]} win_rate={rate(only_r_r[1], only_r_r[2]):.6f}"
    )

    (out_dir / "REPORT.md").write_text("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
