#!/usr/bin/env python3
"""Rolling 21-day sigma evaluation for the window-edge pct_diff feature (training schema).

Purpose:
- Compare dynamic thresholds (rolling mean/std over last N days) vs global thresholds.

Definition:
- Event starts at 15m boundaries: t0 where minute in {0,15,30,45}
- Feature: pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100
- Outcome: 15m candle direction (close@t0+14m vs open@t0), flats excluded

For each event time t0, compute rolling stats over prior `lookback_days` of events:
- mu = mean(pct_diff) over (t0 - lookback_days, t0)
- sd = stddev_samp(pct_diff) over the same window
- Exclude the current row from the window

Then for each sigma k:
- UP prediction if pct_diff > mu + k*sd
- DOWN prediction if pct_diff < mu - k*sd

Outputs a run folder under scripts/output.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SIGMAS_DEFAULT = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback-days", type=int, default=21)
    ap.add_argument(
        "--min-n",
        type=int,
        default=500,
        help="Minimum number of prior events required in the rolling window to score a row.",
    )
    ap.add_argument(
        "--sigmas",
        default=",".join(str(x) for x in SIGMAS_DEFAULT),
        help="Comma-separated sigma thresholds to evaluate.",
    )
    args = ap.parse_args()

    sigmas = [float(x.strip()) for x in args.sigmas.split(",") if x.strip()]
    lookback_days = int(args.lookback_days)
    min_n = int(args.min_n)

    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "window_edge_rolling" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    values_sql = ",".join(f"({s}::float8)" for s in sigmas)

    sql = f"""
with candles as (
  select
    c.symbol,
    c.open_time as t0,
    case
      when c.close > c.open then 1
      when c.close < c.open then 0
      else null
    end as outcome_up
  from training.spot_15m c
  where c.symbol in ('BTC','ETH')
    and extract(second from c.open_time) = 0
    and extract(minute from c.open_time) in (0,15,30,45)
    and c.open is not null and c.close is not null
), events as (
  select
    b.symbol,
    b.t0,
    b.outcome_up,
    ((m_post.close - m_pre.open) / nullif(m_pre.open, 0.0)) * 100.0 as pct_diff
  from candles b
  join training.spot_1m m_pre
    on m_pre.symbol = b.symbol
   and m_pre.ts = b.t0 - interval '3 minutes'
  join training.spot_1m m_post
    on m_post.symbol = b.symbol
   and m_post.ts = b.t0 + interval '1 minute'
  where b.outcome_up is not null
    and m_pre.open is not null and m_post.close is not null
), roll as (
  select
    e.*,
    avg(pct_diff) over w as mu_roll,
    stddev_samp(pct_diff) over w as sd_roll,
    count(*) over w as n_roll
  from events e
  window w as (
    partition by symbol
    order by t0
    range between interval '{lookback_days} days' preceding and interval '1 microsecond' preceding
  )
), eligible as (
  select *
  from roll
  where sd_roll is not null and sd_roll > 0
    and n_roll >= {min_n}
), params as (
  select * from (values {values_sql}) v(k)
), base as (
  select
    symbol,
    count(*)::bigint as n_eligible,
    min(n_roll)::bigint as min_n_roll,
    round(avg(n_roll)::numeric, 1)::float8 as avg_n_roll
  from eligible
  group by 1
), up_side as (
  select
    e.symbol,
    p.k as sigma,
    count(*) filter (where e.pct_diff > e.mu_roll + p.k*e.sd_roll)::bigint as n_pred,
    round((100.0 * count(*) filter (where e.pct_diff > e.mu_roll + p.k*e.sd_roll) / nullif(count(*),0))::numeric, 6)::float8 as coverage_pct,
    round((100.0 * avg(e.outcome_up::float8) filter (where e.pct_diff > e.mu_roll + p.k*e.sd_roll))::numeric, 4)::float8 as accuracy_pct
  from eligible e
  cross join params p
  group by 1,2
), down_side as (
  select
    e.symbol,
    p.k as sigma,
    count(*) filter (where e.pct_diff < e.mu_roll - p.k*e.sd_roll)::bigint as n_pred,
    round((100.0 * count(*) filter (where e.pct_diff < e.mu_roll - p.k*e.sd_roll) / nullif(count(*),0))::numeric, 6)::float8 as coverage_pct,
    round((100.0 * avg((1 - e.outcome_up)::float8) filter (where e.pct_diff < e.mu_roll - p.k*e.sd_roll))::numeric, 4)::float8 as accuracy_pct
  from eligible e
  cross join params p
  group by 1,2
)
select
  b.symbol,
  b.n_eligible,
  b.min_n_roll,
  b.avg_n_roll,
  'UP' as side,
  u.sigma,
  u.n_pred,
  u.coverage_pct,
  u.accuracy_pct
from base b
join up_side u using (symbol)

union all

select
  b.symbol,
  b.n_eligible,
  b.min_n_roll,
  b.avg_n_roll,
  'DOWN' as side,
  d.sigma,
  d.n_pred,
  d.coverage_pct,
  d.accuracy_pct
from base b
join down_side d using (symbol)

order by symbol, side, sigma;
"""

    out_csv = out_dir / "rolling_results.csv"
    psql_copy(db_url, sql, out_csv)

    # Write a tight report.
    rows = list(csv.DictReader(out_csv.open()))
    meta = {
        "lookback_days": lookback_days,
        "min_n": min_n,
        "sigmas": sigmas,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(out_dir),
    }

    md = []
    md.append("# Rolling Window-Edge Sigma Eval (Training Schema)")
    md.append("")
    md.append(f"Run: `{out_dir}`")
    md.append("")
    md.append(f"lookback_days: `{lookback_days}`")
    md.append(f"min_n (required prior events): `{min_n}`")
    md.append(f"sigmas: `{', '.join(str(s) for s in sigmas)}`")
    md.append("")
    md.append("Feature: `pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100`")
    md.append("Outcome: 15m candle direction at quarter-hour boundaries (`:00/:15/:30/:45`), flats excluded")
    md.append("")

    # Summarize per symbol.
    by_symbol = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append(r)

    for sym in sorted(by_symbol.keys()):
        md.append(f"## {sym}")
        md.append("")
        # eligible rows are repeated; pick first
        first = by_symbol[sym][0]
        md.append(
            f"eligible_scored_events: `{first['n_eligible']}` (rolling window n: min `{first['min_n_roll']}`, avg `{first['avg_n_roll']}`)"
        )
        md.append("")
        md.append("side | sigma | n_pred | coverage_pct | accuracy_pct")
        md.append("---|---:|---:|---:|---:")
        for r in by_symbol[sym]:
            md.append(
                f"{r['side']} | {r['sigma']} | {r['n_pred']} | {r['coverage_pct']} | {r['accuracy_pct']}"
            )
        md.append("")

    (out_dir / "REPORT.md").write_text("\n".join(md) + "\n")
    (out_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
