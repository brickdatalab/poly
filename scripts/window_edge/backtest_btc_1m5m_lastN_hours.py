#!/usr/bin/env python3
"""Backtest BTC 1m_5m boundary-return signal over last N hours.

Signal setup:
- Feature (training + validation): ((close@t0+1m - open@t0-4m) / open@t0-4m) * 100
- Event t0 grid: :00/:15/:30/:45
- Label: y_up = 1 if close(t0->t0+14m) > open(t0) else 0
- Thresholding: z-score vs frozen TRAINING mean/std; trigger when |z| >= min_sigma
  - z > 0 => UP prediction
  - z < 0 => DOWN prediction

Outputs:
- scripts/output/window_edge_1m5m_lastN/<UTC>/REPORT.md
- scripts/output/window_edge_1m5m_lastN/<UTC>/events.csv
- scripts/output/window_edge_1m5m_lastN/<UTC>/summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_db_url(env_path: Path) -> str:
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_copy_to_csv(db_url: str, sql: str, out_csv: Path) -> None:
    q = sql.strip()
    if q.endswith(";"):
        q = q[:-1]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "psql",
        db_url,
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-c",
        f"\\copy ({q}) TO STDOUT WITH CSV HEADER",
    ]
    with out_csv.open("w", newline="") as f:
        subprocess.check_call(cmd, stdout=f)


def training_sql(symbol: str = "BTC") -> str:
    return f"""
with events as (
  select
    s15.open_time as t0,
    case
      when s15.close > s15.open then 1
      when s15.close < s15.open then 0
      else null
    end as y_up
  from training.spot_15m s15
  where s15.symbol = '{symbol}'
    and extract(second from s15.open_time) = 0
    and extract(minute from s15.open_time) in (0,15,30,45)
    and s15.open is not null and s15.close is not null
),
joined as (
  select
    e.t0,
    e.y_up,
    ((m_end.close - m_start.open) / nullif(m_start.open, 0.0)) * 100.0 as feature_pct
  from events e
  join training.spot_1m m_start
    on m_start.symbol = '{symbol}'
   and m_start.ts = e.t0 + interval '-4 minutes'
  join training.spot_1m m_end
    on m_end.symbol = '{symbol}'
   and m_end.ts = e.t0 + interval '1 minute'
  where e.y_up is not null
    and m_start.open is not null
    and m_end.close is not null
)
select t0, y_up, feature_pct
from joined
order by t0
"""


def validation_sql(hours: int, pair: str = "BTC-USD") -> str:
    return f"""
with events as (
  select
    o15.bucket_time as t0,
    case
      when o15.close > o15.open then 1
      when o15.close < o15.open then 0
      else null
    end as y_up
  from indicators.ohlcv_15m o15
  where o15.pair = '{pair}'
    and extract(second from o15.bucket_time) = 0
    and extract(minute from o15.bucket_time) in (0,15,30,45)
    and o15.bucket_time >= date_trunc('minute', now()) - interval '{hours} hours'
    and o15.bucket_time <  date_trunc('minute', now())
    and o15.open is not null and o15.close is not null
),
joined as (
  select
    e.t0,
    e.y_up,
    ((m_end.close::float8 - m_start.open::float8) / nullif(m_start.open::float8, 0.0)) * 100.0 as feature_pct
  from events e
  join indicators.ohlcv_1m m_start
    on m_start.pair = '{pair}'
   and m_start.bucket_time = e.t0 + interval '-4 minutes'
  join indicators.ohlcv_1m m_end
    on m_end.pair = '{pair}'
   and m_end.bucket_time = e.t0 + interval '1 minute'
  where e.y_up is not null
    and m_start.open is not null
    and m_end.close is not null
)
select t0, y_up, feature_pct
from joined
order by t0
"""


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        r = csv.DictReader(f)
        for d in r:
            rows.append(
                {
                    "t0": d["t0"],
                    "y_up": int(d["y_up"]),
                    "feature_pct": float(d["feature_pct"]),
                }
            )
    return rows


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def std_samp(xs: list[float], mu: float) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else float("nan")


def run(hours: int, min_sigma: float) -> Path:
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root / ".env")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "window_edge_1m5m_lastN" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    tr_csv = out_dir / "training_events.csv"
    va_csv = out_dir / "validation_events.csv"
    psql_copy_to_csv(db_url, training_sql("BTC"), tr_csv)
    psql_copy_to_csv(db_url, validation_sql(hours, "BTC-USD"), va_csv)

    tr_rows = load_rows(tr_csv)
    va_rows = load_rows(va_csv)
    tr_vals = [r["feature_pct"] for r in tr_rows]
    mu = mean(tr_vals)
    sd = std_samp(tr_vals, mu)

    events: list[dict[str, Any]] = []
    for r in va_rows:
        z = (r["feature_pct"] - mu) / sd if sd and sd == sd else float("nan")
        pred: str | None = None
        if z == z and abs(z) >= min_sigma and z != 0:
            pred = "UP" if z > 0 else "DOWN"
        correct: int | None = None
        if pred == "UP":
            correct = 1 if r["y_up"] == 1 else 0
        elif pred == "DOWN":
            correct = 1 if r["y_up"] == 0 else 0
        events.append(
            {
                "t0": r["t0"],
                "y_up": r["y_up"],
                "feature_pct": r["feature_pct"],
                "zscore": z,
                "prediction": pred,
                "correct": correct,
            }
        )

    fired = [e for e in events if e["prediction"] is not None]
    n_total = len(events)
    n_triggered = len(fired)
    wins = sum(1 for e in fired if e["correct"] == 1)
    losses = sum(1 for e in fired if e["correct"] == 0)

    def side_stats(side: str) -> dict[str, Any]:
        s = [e for e in fired if e["prediction"] == side]
        s_w = sum(1 for e in s if e["correct"] == 1)
        s_l = sum(1 for e in s if e["correct"] == 0)
        return {
            "triggered": len(s),
            "accurate": s_w,
            "not_accurate": s_l,
            "win_rate_pct": pct(s_w, len(s)),
        }

    up = side_stats("UP")
    down = side_stats("DOWN")

    with (out_dir / "events.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t0", "y_up", "feature_pct", "zscore", "prediction", "correct"])
        for e in events:
            w.writerow([e["t0"], e["y_up"], e["feature_pct"], e["zscore"], e["prediction"], e["correct"]])

    summary = {
        "experiment": "1m_5m_boundary_return",
        "symbol": "BTC",
        "hours": hours,
        "min_sigma": min_sigma,
        "training": {
            "n_events": len(tr_rows),
            "mean_pct": mu,
            "std_pct": sd,
        },
        "validation": {
            "n_events": n_total,
            "triggered": n_triggered,
            "accurate": wins,
            "not_accurate": losses,
            "trigger_rate_pct": pct(n_triggered, n_total),
            "win_rate_pct": pct(wins, n_triggered),
            "by_signal": {"UP": up, "DOWN": down},
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    md: list[str] = []
    md.append("# BTC 1m_5m Boundary Return Backtest")
    md.append("")
    md.append(f"Run: `{out_dir}`")
    md.append("")
    md.append("## Config")
    md.append("")
    md.append(f"- hours: `{hours}`")
    md.append(f"- min_sigma: `{min_sigma}`")
    md.append(f"- feature: `((close@t0+1m - open@t0-4m) / open@t0-4m) * 100`")
    md.append(f"- trigger: `|z| >= {min_sigma}` (z from frozen training mean/std)")
    md.append("")
    md.append("## Training Stats")
    md.append("")
    md.append(f"- n_events: `{len(tr_rows)}`")
    md.append(f"- mean_pct: `{mu:.12f}`")
    md.append(f"- std_pct: `{sd:.12f}`")
    md.append("")
    md.append("## Validation Summary")
    md.append("")
    md.append(f"- n_total_events: `{n_total}`")
    md.append(f"- triggered: `{n_triggered}`")
    md.append(f"- accurate: `{wins}`")
    md.append(f"- not_accurate: `{losses}`")
    md.append(f"- trigger_rate_pct: `{pct(n_triggered, n_total):.6f}%`")
    md.append(f"- win_rate_pct: `{pct(wins, n_triggered):.6f}%`")
    md.append("")
    md.append("## By Signal")
    md.append("")
    md.append(
        f"- UP: triggered `{up['triggered']}`, accurate `{up['accurate']}`, "
        f"not_accurate `{up['not_accurate']}`, win_rate `{up['win_rate_pct']:.6f}%`"
    )
    md.append(
        f"- DOWN: triggered `{down['triggered']}`, accurate `{down['accurate']}`, "
        f"not_accurate `{down['not_accurate']}`, win_rate `{down['win_rate_pct']:.6f}%`"
    )
    (out_dir / "REPORT.md").write_text("\n".join(md) + "\n")

    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="BTC 1m_5m boundary-return backtest over last N hours.")
    ap.add_argument("--hours", type=int, default=72, help="Validation lookback window in hours.")
    ap.add_argument("--min-sigma", type=float, default=0.25, help="Minimum absolute z-score to trigger a signal.")
    args = ap.parse_args()

    out_dir = run(hours=int(args.hours), min_sigma=float(args.min_sigma))
    print(str(out_dir))


if __name__ == "__main__":
    main()

