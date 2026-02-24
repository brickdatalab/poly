#!/usr/bin/env python3
"""Analyze whether the 4-minute boundary move (:57 open -> :01 close) relates to the :00->:14 15m candle outcome.

Training schema only. Excludes SOL.

Outputs a run directory with:
- REPORT.md (human summary)
- bins_<SYMBOL>.csv (decile bin conditional up-rate)
- thresholds_<SYMBOL>.csv (sweep for up/down precision vs coverage)
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np


def load_db_url(env_path: Path) -> str:
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_copy_to_csv(db_url: str, sql: str, out_csv: Path) -> None:
    # psql \copy expects a query without a trailing ';' inside the parentheses.
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
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
    with out_csv.open("w", newline="") as f:
        subprocess.check_call(cmd, stdout=f)


@dataclass
class Row:
    t0: str
    pct_diff: float
    y_up: int


def load_rows(csv_path: Path) -> list[Row]:
    rows: list[Row] = []
    with csv_path.open() as f:
        r = csv.DictReader(f)
        for d in r:
            pct = float(d["pct_diff_57_to_01"])
            y = int(d["y_up"])
            rows.append(Row(t0=d["t0"], pct_diff=pct, y_up=y))
    return rows


def auc_roc(y: np.ndarray, score: np.ndarray) -> float:
    # Fast AUC for binary labels {0,1} via rank statistics.
    # Returns NaN if degenerate.
    y = y.astype(int)
    n1 = int(y.sum())
    n0 = int((1 - y).sum())
    if n0 == 0 or n1 == 0:
        return float("nan")
    order = np.argsort(score)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    # Handle ties: average ranks for tied scores
    # N is small (~26k), so a simple tie fix is fine.
    s_sorted = score[order]
    i = 0
    while i < len(s_sorted):
        j = i + 1
        while j < len(s_sorted) and s_sorted[j] == s_sorted[i]:
            j += 1
        if j - i > 1:
            avg_rank = (i + 1 + j) / 2.0
            ranks[order[i:j]] = avg_rank
        i = j
    sum_ranks_pos = ranks[y == 1].sum()
    auc = (sum_ranks_pos - n1 * (n1 + 1) / 2.0) / (n0 * n1)
    return float(auc)


def spearman_corr(x: np.ndarray, y: np.ndarray) -> float:
    # Spearman = Pearson of ranks.
    rx = x.argsort().argsort().astype(float)
    ry = y.argsort().argsort().astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def threshold_sweep(pct: np.ndarray, y_up: np.ndarray, steps: int = 401):
    # Sweep thresholds across percentiles of pct, but evenly spaced in value is fine.
    lo, hi = np.nanpercentile(pct, [0.5, 99.5])
    ts = np.linspace(lo, hi, steps)
    out = []
    n = len(pct)
    for t in ts:
        up_mask = pct >= t
        dn_mask = pct <= -t  # symmetric opposite magnitude
        # precision_up = P(up | pct>=t)
        n_up = int(up_mask.sum())
        n_dn = int(dn_mask.sum())
        prec_up = float(y_up[up_mask].mean()) if n_up else float("nan")
        prec_dn = float((1 - y_up[dn_mask]).mean()) if n_dn else float("nan")
        cov_up = n_up / n
        cov_dn = n_dn / n
        out.append((t, n_up, cov_up, prec_up, n_dn, cov_dn, prec_dn))
    return out


def decile_bins(pct: np.ndarray, y_up: np.ndarray, n_bins: int = 10):
    qs = np.linspace(0, 1, n_bins + 1)
    edges = np.quantile(pct, qs)
    # Make edges strictly increasing (guard repeated edges from ties)
    edges2 = [edges[0]]
    for e in edges[1:]:
        if e <= edges2[-1]:
            e = np.nextafter(edges2[-1], float("inf"))
        edges2.append(e)
    edges = np.array(edges2)

    bins = []
    for i in range(n_bins):
        a, b = float(edges[i]), float(edges[i + 1])
        if i == n_bins - 1:
            mask = (pct >= a) & (pct <= b)
        else:
            mask = (pct >= a) & (pct < b)
        n = int(mask.sum())
        if n == 0:
            bins.append((i, a, b, 0, float("nan"), float("nan")))
            continue
        bins.append((
            i,
            a,
            b,
            n,
            float(pct[mask].mean()),
            float(y_up[mask].mean()),
        ))
    return bins


def fmt_pct(x: float, digits: int = 4) -> str:
    if x != x:
        return "nan"
    return f"{x:.{digits}f}%"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root / ".env")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "window_edge" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    report_lines: list[str] = []
    report_lines.append("# Window Edge Scan (Training Schema)")
    report_lines.append("")
    report_lines.append(f"Run: `{out_dir}`")
    report_lines.append("")
    report_lines.append("Feature: `pct_diff_57_to_01 = ((close@01 - open@57) / open@57) * 100`")
    report_lines.append("Label: `y_up = 1 if 15m close(:14) > open(:00) else 0` for candles starting at `:00` only")
    report_lines.append("")

    for symbol in ["BTC", "ETH"]:
        sql = f"""
with base as (
  select
    c.open_time as t0,
    case
      when c.close > c.open then 1
      when c.close < c.open then 0
      else null
    end as y_up
  from training.spot_15m c
  where c.symbol = '{symbol}'
    and extract(minute from c.open_time) = 0
    and extract(second from c.open_time) = 0
    and c.open is not null and c.close is not null
), joined as (
  select
    b.t0,
    b.y_up,
    ((m01.close - m57.open) / nullif(m57.open, 0.0)) * 100.0 as pct_diff_57_to_01
  from base b
  join training.spot_1m m57
    on m57.symbol = '{symbol}'
   and m57.ts = b.t0 - interval '3 minutes'
  join training.spot_1m m01
    on m01.symbol = '{symbol}'
   and m01.ts = b.t0 + interval '1 minute'
  where b.y_up is not null
    and m57.open is not null and m01.close is not null
)
select
  t0,
  y_up,
  pct_diff_57_to_01
from joined
order by t0;
"""
        csv_path = out_dir / f"dataset_{symbol}.csv"
        psql_copy_to_csv(db_url, sql, csv_path)
        rows = load_rows(csv_path)

        pct = np.array([r.pct_diff for r in rows], dtype=float)
        y = np.array([r.y_up for r in rows], dtype=int)

        n = len(y)
        up_rate = float(y.mean())
        corr = float(np.corrcoef(pct, y)[0, 1])
        spear = spearman_corr(pct, y.astype(float))
        auc = auc_roc(y, pct)

        report_lines.append(f"## {symbol}")
        report_lines.append("")
        report_lines.append(f"n: `{n}`")
        report_lines.append(f"base up-rate: `{up_rate:.6f}`")
        report_lines.append(f"pearson corr(pct_diff, y_up): `{corr:.6f}`")
        report_lines.append(f"spearman corr(pct_diff, y_up): `{spear:.6f}`")
        report_lines.append(f"AUC(pct_diff as score for up): `{auc:.6f}`")
        report_lines.append("")

        # Decile bins for trend shape
        bins = decile_bins(pct, y, 10)
        bins_csv = out_dir / f"bins_{symbol}.csv"
        with bins_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["bin", "edge_lo_pct", "edge_hi_pct", "n", "mean_pct_diff", "up_rate"])
            for b in bins:
                w.writerow(b)

        report_lines.append("Deciles (increasing pct_diff):")
        for i, lo, hi, bn, mean_pct, ur in bins:
            report_lines.append(
                f"- bin {i}: [{lo:.4f}%, {hi:.4f}%) n={bn} mean={mean_pct:.4f}% up_rate={ur:.4f}"
            )
        report_lines.append("")

        # Threshold sweep (symmetric)
        sweep = threshold_sweep(pct, y, steps=301)
        thr_csv = out_dir / f"thresholds_{symbol}.csv"
        with thr_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "t_pct",
                "n_up",
                "coverage_up",
                "precision_up",
                "n_down",
                "coverage_down",
                "precision_down",
            ])
            for row in sweep:
                w.writerow(row)

        # Report a few interesting operating points:
        # 1) best precision_up among thresholds with coverage_up >= 1%
        # 2) best precision_down among thresholds with coverage_down >= 1%
        def best(rows, side: str):
            best_row = None
            for t, n_up, cov_up, prec_up, n_dn, cov_dn, prec_dn in rows:
                if side == "up":
                    if cov_up < 0.01 or np.isnan(prec_up):
                        continue
                    score = prec_up
                    cur = (score, cov_up, t, n_up)
                else:
                    if cov_dn < 0.01 or np.isnan(prec_dn):
                        continue
                    score = prec_dn
                    cur = (score, cov_dn, t, n_dn)
                if best_row is None or cur[0] > best_row[0]:
                    best_row = cur
            return best_row

        b_up = best(sweep, "up")
        b_dn = best(sweep, "down")
        if b_up:
            prec, cov, t, n_up = b_up
            report_lines.append(
                f"Best UP precision (coverage>=1%): precision={prec:.4f} coverage={cov:.4f} threshold t={t:.4f}% (n={n_up})"
            )
        if b_dn:
            prec, cov, t, n_dn = b_dn
            report_lines.append(
                f"Best DOWN precision (coverage>=1%): precision={prec:.4f} coverage={cov:.4f} threshold t={t:.4f}% (n={n_dn})"
            )
        report_lines.append("")

    (out_dir / "REPORT.md").write_text("\n".join(report_lines) + "\n")


if __name__ == "__main__":
    main()
