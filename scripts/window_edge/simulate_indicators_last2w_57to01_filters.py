#!/usr/bin/env python3
"""Apply the training-derived 57->01 boundary-momentum filters to indicators schema.

Rule form per pair:
- compute pct_diff_57_to_01 = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100
- consider only 15m candles starting at :00 (event :00 -> :15)
- predict UP if pct_diff >= up_threshold
- predict DOWN if pct_diff <= -down_threshold
- otherwise abstain

Evaluation window: last 14 days in indicators schema (relative to DB now()).

Outputs:
- scripts/output/window_edge_indicators/<UTC>/REPORT.md
- scripts/output/window_edge_indicators/<UTC>/predictions_<PAIR>.csv
"""

from __future__ import annotations

import csv
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


THRESHOLDS = {
    # From training scan REPORT.md (coverage>=1% operating points)
    "BTC-USD": {"up_t": 0.5735, "down_t": 0.5487},
    "ETH-USD": {"up_t": 0.7305, "down_t": 0.6740},
}


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


def psql_copy(db_url: str, sql: str, out_csv: Path) -> None:
    sql = sql.strip()
    if sql.endswith(';'):
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
    with out_csv.open('w', newline='') as f:
        subprocess.check_call(cmd, stdout=f)


@dataclass
class Stats:
    pair: str
    n_total: int
    n_scored: int
    n_pred: int
    wins: int
    losses: int
    abstain: int
    pred_up: int
    pred_down: int


def compute_stats(csv_path: Path, pair: str) -> Stats:
    n_total = n_scored = n_pred = wins = losses = abstain = pred_up = pred_down = 0
    with csv_path.open() as f:
        r = csv.DictReader(f)
        for d in r:
            n_total += 1
            # outcome_up is 0/1 always (we filter flats out in SQL)
            n_scored += 1
            pred = d["pred"]
            if pred == "":
                abstain += 1
                continue
            n_pred += 1
            p = int(pred)
            y = int(d["outcome_up"])
            if p == 1:
                pred_up += 1
            else:
                pred_down += 1
            if p == y:
                wins += 1
            else:
                losses += 1

    return Stats(
        pair=pair,
        n_total=n_total,
        n_scored=n_scored,
        n_pred=n_pred,
        wins=wins,
        losses=losses,
        abstain=abstain,
        pred_up=pred_up,
        pred_down=pred_down,
    )


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root / ".env")

    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = root / 'scripts' / 'output' / 'window_edge_indicators' / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    report = []
    report.append('# Indicators Backtest: 57->01 Filters (Last 14 Days)')
    report.append('')
    report.append(f'Run: `{out_dir}`')
    report.append('')
    report.append('Rule:')
    report.append('- pct_diff_57_to_01 = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100')
    report.append('- For 15m candles starting at :00 only (event :00 -> :15):')
    report.append('  - predict UP if pct_diff >= up_t')
    report.append('  - predict DOWN if pct_diff <= -down_t')
    report.append('  - else abstain')
    report.append('')

    for pair, th in THRESHOLDS.items():
        up_t = float(th['up_t'])
        down_t = float(th['down_t'])

        # window: last 14 days relative to DB now()
        sql = f"""
with c15 as (
  select
    bucket_time as t0,
    open::float8 as open_00,
    close::float8 as close_14,
    case
      when close > open then 1
      when close < open then 0
      else null
    end as outcome_up
  from indicators.ohlcv_15m
  where pair = '{pair}'
    and bucket_time >= (now() - interval '14 days')
    and extract(minute from bucket_time) = 0
    and extract(second from bucket_time) = 0
), joined as (
  select
    c15.t0,
    c15.outcome_up,
    m57.open::float8 as open_57,
    m01.close::float8 as close_01,
    ((m01.close::float8 - m57.open::float8) / nullif(m57.open::float8, 0.0)) * 100.0 as pct_diff_57_to_01,
    case
      when ((m01.close::float8 - m57.open::float8) / nullif(m57.open::float8, 0.0)) * 100.0 >= {up_t} then 1
      when ((m01.close::float8 - m57.open::float8) / nullif(m57.open::float8, 0.0)) * 100.0 <= -{down_t} then 0
      else null
    end as pred
  from c15
  join indicators.ohlcv_1m m57
    on m57.pair = '{pair}'
   and m57.bucket_time = c15.t0 - interval '3 minutes'
  join indicators.ohlcv_1m m01
    on m01.pair = '{pair}'
   and m01.bucket_time = c15.t0 + interval '1 minute'
  where c15.outcome_up is not null
)
select
  t0,
  outcome_up,
  pct_diff_57_to_01,
  pred
from joined
order by t0;
"""

        out_csv = out_dir / f'predictions_{pair}.csv'
        psql_copy(db_url, sql, out_csv)
        st = compute_stats(out_csv, pair)

        win_rate = (st.wins / st.n_pred) if st.n_pred else float('nan')
        net_profit = st.wins - st.losses
        total_bet = st.n_pred
        roi = (net_profit / total_bet) if total_bet else float('nan')

        report.append(f'## {pair}')
        report.append('')
        report.append(f"thresholds: up_t={up_t:.4f}%, down_t={down_t:.4f}%")
        report.append(f"scored candles (last 14d, :00 starts, excluding flats): {st.n_scored}")
        report.append(f"predictions: {st.n_pred} (UP {st.pred_up}, DOWN {st.pred_down}), abstained: {st.abstain}")
        report.append(f"accurate (wins): {st.wins}")
        report.append(f"inaccurate (losses): {st.losses}")
        report.append(f"win-rate on predictions: {win_rate:.6f}")
        report.append(f"$1 per prediction: total bet=${total_bet}, net=${net_profit}, ROI={roi:.6f}")
        report.append('')

    (out_dir / 'REPORT.md').write_text('\n'.join(report) + '\n')


if __name__ == '__main__':
    main()
