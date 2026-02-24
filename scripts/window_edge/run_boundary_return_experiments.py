#!/usr/bin/env python3
"""Run boundary-return experiments from docs/discoveries/experiments.yaml.

For each experiment:
- Build training dataset (training schema, BTC) using 1m joins around quarter-hour events.
- Compute global feature stats (min/max/mean/std).
- Sweep sigma ladder for UP/DOWN trigger accuracy and coverage.
- Freeze training mean/std and evaluate triggers on indicators last 48h.
- Produce per-experiment artifacts and top-level summary report.
"""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SIGMAS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


@dataclass(frozen=True)
class Experiment:
    name: str
    symbol: str
    start_offset_min: int
    end_offset_min: int
    start_field: str
    end_field: str
    validation_window: str


def load_db_url(env_path: Path) -> str:
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


def parse_experiments(path: Path) -> list[Experiment]:
    obj = yaml.safe_load(path.read_text())
    exps_raw = obj.get("experiments", [])
    out: list[Experiment] = []
    for e in exps_raw:
        feature = e["feature"]
        eval_cfg = e["evaluation"]
        out.append(
            Experiment(
                name=str(e["experiment_name"]),
                symbol=str(e["symbol"]),
                start_offset_min=int(feature["start_offset_min"]),
                end_offset_min=int(feature["end_offset_min"]),
                start_field=str(feature["start_field"]),
                end_field=str(feature["end_field"]),
                validation_window=str(eval_cfg["validation_window"]),
            )
        )
    return out


def _pair_from_symbol(symbol: str) -> str:
    return f"{symbol}-USD"


def _end_close_offset_min(end_field: str, end_offset_min: int) -> int:
    # For "close_of_prev_*", end boundary is prior minute relative to end_offset.
    if end_field.startswith("close_of_prev_"):
        return end_offset_min - 1
    return end_offset_min


def training_sql(exp: Experiment) -> str:
    s_off = exp.start_offset_min
    e_off = _end_close_offset_min(exp.end_field, exp.end_offset_min)
    symbol = exp.symbol
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
    and s15.open is not null
    and s15.close is not null
),
joined as (
  select
    e.t0,
    e.y_up,
    ((m_end.close - m_start.open) / nullif(m_start.open, 0.0)) * 100.0 as feature_pct
  from events e
  join training.spot_1m m_start
    on m_start.symbol = '{symbol}'
   and m_start.ts = e.t0 + interval '{s_off} minutes'
  join training.spot_1m m_end
    on m_end.symbol = '{symbol}'
   and m_end.ts = e.t0 + interval '{e_off} minutes'
  where e.y_up is not null
    and m_start.open is not null
    and m_end.close is not null
)
select t0, y_up, feature_pct
from joined
order by t0;
"""


def validation_sql(exp: Experiment) -> str:
    s_off = exp.start_offset_min
    e_off = _end_close_offset_min(exp.end_field, exp.end_offset_min)
    pair = _pair_from_symbol(exp.symbol)
    if exp.validation_window != "last_48h":
        raise ValueError(f"Unsupported validation_window: {exp.validation_window}")

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
    and o15.bucket_time >= date_trunc('minute', now()) - interval '48 hours'
    and o15.bucket_time <  date_trunc('minute', now())
    and o15.open is not null
    and o15.close is not null
),
joined as (
  select
    e.t0,
    e.y_up,
    ((m_end.close::float8 - m_start.open::float8) / nullif(m_start.open::float8, 0.0)) * 100.0 as feature_pct
  from events e
  join indicators.ohlcv_1m m_start
    on m_start.pair = '{pair}'
   and m_start.bucket_time = e.t0 + interval '{s_off} minutes'
  join indicators.ohlcv_1m m_end
    on m_end.pair = '{pair}'
   and m_end.bucket_time = e.t0 + interval '{e_off} minutes'
  where e.y_up is not null
    and m_start.open is not null
    and m_end.close is not null
)
select t0, y_up, feature_pct
from joined
order by t0;
"""


def _load_rows(csv_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with csv_path.open() as f:
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


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _std_samp(xs: list[float], mu: float) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)


def _sweep_sigma(rows: list[dict[str, Any]], mu: float, sd: float) -> list[dict[str, Any]]:
    n_total = len(rows)
    out: list[dict[str, Any]] = []
    for side in ("DOWN", "UP"):
        for k in SIGMAS:
            if side == "UP":
                thr = mu + k * sd
                pred = [r for r in rows if r["feature_pct"] > thr]
                wins = sum(1 for r in pred if r["y_up"] == 1)
            else:
                thr = mu - k * sd
                pred = [r for r in rows if r["feature_pct"] < thr]
                wins = sum(1 for r in pred if r["y_up"] == 0)
            n_pred = len(pred)
            coverage = (100.0 * n_pred / n_total) if n_total else float("nan")
            acc = (100.0 * wins / n_pred) if n_pred else float("nan")
            losses = n_pred - wins
            out.append(
                {
                    "side": side,
                    "sigma": k,
                    "threshold_pct": thr,
                    "n_total": n_total,
                    "n_pred": n_pred,
                    "coverage_pct": coverage,
                    "wins": wins,
                    "losses": losses,
                    "accuracy_pct": acc,
                }
            )
    return out


def _operational_last48(rows: list[dict[str, Any]], mu: float, sd: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for r in rows:
        z = (r["feature_pct"] - mu) / sd if sd and sd == sd else float("nan")
        chosen_sigma = None
        for k in sorted(SIGMAS, reverse=True):
            if abs(z) >= k:
                chosen_sigma = k
                break
        pred: str | None
        if chosen_sigma is None or z != z or z == 0:
            pred = None
        elif z > 0:
            pred = "UP"
        else:
            pred = "DOWN"

        correct: int | None
        if pred is None:
            correct = None
        elif pred == "UP":
            correct = 1 if r["y_up"] == 1 else 0
        else:
            correct = 1 if r["y_up"] == 0 else 0

        events.append(
            {
                "t0": r["t0"],
                "feature_pct": r["feature_pct"],
                "y_up": r["y_up"],
                "zscore": z,
                "prediction": pred,
                "sigma": chosen_sigma,
                "correct": correct,
            }
        )

    fired = [e for e in events if e["prediction"] is not None]
    wins = sum(1 for e in fired if e["correct"] == 1)
    losses = sum(1 for e in fired if e["correct"] == 0)
    wr = (100.0 * wins / len(fired)) if fired else float("nan")

    sigma_dist: dict[float, dict[str, int]] = {}
    for e in fired:
        k = float(e["sigma"])
        sigma_dist.setdefault(k, {"n": 0, "wins": 0, "losses": 0})
        sigma_dist[k]["n"] += 1
        if e["correct"] == 1:
            sigma_dist[k]["wins"] += 1
        else:
            sigma_dist[k]["losses"] += 1

    summary = {
        "n_events": len(rows),
        "n_triggered": len(fired),
        "n_wins": wins,
        "n_losses": losses,
        "win_rate_pct": wr,
        "trigger_rate_pct": (100.0 * len(fired) / len(rows)) if rows else float("nan"),
        "sigma_distribution": sigma_dist,
    }
    return events, summary


def _best_points(sweep: list[dict[str, Any]], min_coverage_pct: float = 0.5) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    for side in ("UP", "DOWN"):
        cand = [
            r
            for r in sweep
            if r["side"] == side and r["n_pred"] > 0 and r["coverage_pct"] >= min_coverage_pct and r["accuracy_pct"] == r["accuracy_pct"]
        ]
        if not cand:
            continue
        cand.sort(key=lambda r: (r["accuracy_pct"], r["coverage_pct"], r["n_pred"]), reverse=True)
        best.append(cand[0])
    return best


def run_one(exp: Experiment, db_url: str, out_root: Path) -> dict[str, Any]:
    exp_dir = out_root / exp.name
    exp_dir.mkdir(parents=True, exist_ok=True)

    train_sql = training_sql(exp)
    val_sql = validation_sql(exp)

    (exp_dir / "training_query.sql").write_text(train_sql + "\n")
    (exp_dir / "validation_query.sql").write_text(val_sql + "\n")

    train_csv = exp_dir / "training_events.csv"
    val_csv = exp_dir / "validation_last48h_events.csv"
    psql_copy_to_csv(db_url, train_sql, train_csv)
    psql_copy_to_csv(db_url, val_sql, val_csv)

    tr_rows = _load_rows(train_csv)
    va_rows = _load_rows(val_csv)
    xs = [r["feature_pct"] for r in tr_rows]

    mu = _mean(xs)
    sd = _std_samp(xs, mu)
    mn = min(xs) if xs else float("nan")
    mx = max(xs) if xs else float("nan")

    tr_sweep = _sweep_sigma(tr_rows, mu, sd)
    va_sweep = _sweep_sigma(va_rows, mu, sd)
    va_events, va_oper = _operational_last48(va_rows, mu, sd)

    _write_csv(
        exp_dir / "training_sigma_sweep.csv",
        ["side", "sigma", "threshold_pct", "n_total", "n_pred", "coverage_pct", "wins", "losses", "accuracy_pct"],
        [[r[k] for k in ["side", "sigma", "threshold_pct", "n_total", "n_pred", "coverage_pct", "wins", "losses", "accuracy_pct"]] for r in tr_sweep],
    )
    _write_csv(
        exp_dir / "validation_sigma_sweep.csv",
        ["side", "sigma", "threshold_pct", "n_total", "n_pred", "coverage_pct", "wins", "losses", "accuracy_pct"],
        [[r[k] for k in ["side", "sigma", "threshold_pct", "n_total", "n_pred", "coverage_pct", "wins", "losses", "accuracy_pct"]] for r in va_sweep],
    )
    _write_csv(
        exp_dir / "validation_operational_events.csv",
        ["t0", "feature_pct", "y_up", "zscore", "prediction", "sigma", "correct"],
        [[r[k] for k in ["t0", "feature_pct", "y_up", "zscore", "prediction", "sigma", "correct"]] for r in va_events],
    )
    (exp_dir / "validation_operational_summary.json").write_text(json.dumps(va_oper, indent=2))

    tr_best = _best_points(tr_sweep, min_coverage_pct=0.5)
    va_best = _best_points(va_sweep, min_coverage_pct=0.5)

    md: list[str] = []
    md.append(f"# Experiment: {exp.name}")
    md.append("")
    md.append(f"symbol: `{exp.symbol}`")
    md.append(f"feature_start_offset_min: `{exp.start_offset_min}`")
    md.append(f"feature_end_offset_min: `{exp.end_offset_min}`")
    md.append(f"end_field: `{exp.end_field}`")
    md.append("")
    md.append("## Training Distribution")
    md.append("")
    md.append(f"n_events: `{len(tr_rows)}`")
    md.append(f"feature_min_pct: `{mn:.6f}`")
    md.append(f"feature_max_pct: `{mx:.6f}`")
    md.append(f"feature_mean_pct: `{mu:.6f}`")
    md.append(f"feature_std_pct: `{sd:.6f}`")
    md.append("")
    md.append("## Training Best Points (coverage >= 0.5%)")
    if not tr_best:
        md.append("- none")
    for r in tr_best:
        md.append(
            f"- {r['side']} @ {r['sigma']}σ: accuracy={r['accuracy_pct']:.4f}% "
            f"coverage={r['coverage_pct']:.4f}% n_pred={r['n_pred']} threshold={r['threshold_pct']:.6f}%"
        )
    md.append("")
    md.append("## Validation Last 48h (Frozen Training Thresholds)")
    md.append("")
    md.append(f"n_events: `{len(va_rows)}`")
    md.append(f"triggered: `{va_oper['n_triggered']}` ({va_oper['trigger_rate_pct']:.4f}%)")
    md.append(f"wins: `{va_oper['n_wins']}`")
    md.append(f"losses: `{va_oper['n_losses']}`")
    md.append(f"win_rate: `{va_oper['win_rate_pct']:.4f}%`")
    md.append("")
    md.append("Best validation points by side (coverage >= 0.5%):")
    if not va_best:
        md.append("- none")
    for r in va_best:
        md.append(
            f"- {r['side']} @ {r['sigma']}σ: accuracy={r['accuracy_pct']:.4f}% "
            f"coverage={r['coverage_pct']:.4f}% n_pred={r['n_pred']}"
        )
    md.append("")
    md.append("Artifacts:")
    md.append(f"- `{(exp_dir / 'training_events.csv').as_posix()}`")
    md.append(f"- `{(exp_dir / 'training_sigma_sweep.csv').as_posix()}`")
    md.append(f"- `{(exp_dir / 'validation_last48h_events.csv').as_posix()}`")
    md.append(f"- `{(exp_dir / 'validation_sigma_sweep.csv').as_posix()}`")
    md.append(f"- `{(exp_dir / 'validation_operational_events.csv').as_posix()}`")
    md.append("")
    (exp_dir / "REPORT.md").write_text("\n".join(md) + "\n")

    return {
        "experiment_name": exp.name,
        "training_n": len(tr_rows),
        "training_mean_pct": mu,
        "training_std_pct": sd,
        "training_best": tr_best,
        "validation_n": len(va_rows),
        "validation_triggered": va_oper["n_triggered"],
        "validation_win_rate_pct": va_oper["win_rate_pct"],
        "validation_best": va_best,
        "out_dir": str(exp_dir),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root / ".env")

    cfg_path = root / "docs" / "discoveries" / "experiments.yaml"
    exps = parse_experiments(cfg_path)
    if not exps:
        raise SystemExit(f"No experiments found in {cfg_path}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = root / "scripts" / "output" / "window_edge_variations" / run_id
    out_root.mkdir(parents=True, exist_ok=True)

    n_workers = min(len(exps), max(1, (os.cpu_count() or 1)))
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = [ex.submit(run_one, e, db_url, out_root) for e in exps]
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda r: r["experiment_name"])
    (out_root / "summary.json").write_text(json.dumps(results, indent=2))

    lines: list[str] = []
    lines.append("# Boundary Return Experiments Summary")
    lines.append("")
    lines.append(f"Run: `{out_root}`")
    lines.append("")
    lines.append("experiment | train_n | train_mean_pct | train_std_pct | val_n | val_triggered | val_trigger_rate_pct | val_win_rate_pct")
    lines.append("---|---:|---:|---:|---:|---:|---:|---:")
    for r in results:
        trig_rate = (100.0 * r["validation_triggered"] / r["validation_n"]) if r["validation_n"] else float("nan")
        lines.append(
            f"{r['experiment_name']} | {r['training_n']} | {r['training_mean_pct']:.6f} | {r['training_std_pct']:.6f} | "
            f"{r['validation_n']} | {r['validation_triggered']} | {trig_rate:.4f} | {r['validation_win_rate_pct']:.4f}"
        )
    lines.append("")
    lines.append("Per-experiment reports:")
    for r in results:
        lines.append(f"- `{Path(r['out_dir']) / 'REPORT.md'}`")
    (out_root / "REPORT.md").write_text("\n".join(lines) + "\n")

    print(str(out_root))


if __name__ == "__main__":
    main()
