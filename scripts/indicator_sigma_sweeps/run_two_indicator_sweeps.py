#!/usr/bin/env python3
"""Run sigma-trigger sweeps for two indicators on TRAINING schema only.

Indicators:
- CVD ROC (cvd_50)
- EMA spread ROC (ema_9 vs ema_21)

For each indicator we run 4 variants:
- lookback=15m, global mu/sd
- lookback=60m, global mu/sd
- lookback=15m, rolling 21d mu/sd (min_n in {500,1000})
- lookback=60m, rolling 21d mu/sd (min_n in {500,1000})

Output:
- scripts/output/indicator_sigma_sweeps/<UTC>/**

This is correlation discovery only. It does not touch indicators schema.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SIGMAS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


@dataclass(frozen=True)
class Variant:
    slug: str
    indicator: str
    lookback_min: int
    normalization: str  # global|rolling
    rolling_days: int | None
    rolling_min_n: int | None


def _load_db_url(env_path: Path) -> str:
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get('SUPABASE_DB_URL')
    if not db_url:
        raise SystemExit('SUPABASE_DB_URL missing in .env')
    return db_url


def _psql_copy(db_url: str, sql: str, out_csv: Path) -> None:
    sql = sql.strip()
    # We'll use server-side COPY to STDOUT (SQL), which is robust to nested parentheses.
    while sql.endswith(';'):
        sql = sql[:-1].rstrip()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        'psql',
        db_url,
        '-v',
        'ON_ERROR_STOP=1',
        '-P',
        'pager=off',
        '-c',
        # Increase statement timeout for heavy window queries.
        f"SET statement_timeout = '30min'; COPY ({sql}) TO STDOUT WITH CSV HEADER",
    ]
    with out_csv.open('w', newline='') as f:
        subprocess.check_call(cmd, stdout=f)


def _values_sigmas() -> str:
    return ','.join(f'({s}::float8)' for s in SIGMAS)


def _feature_expr(indicator: str, alias_cur: str, alias_prev: str) -> str:
    if indicator == 'cvd_50_roc':
        return f"({alias_cur}.cvd_50 - {alias_prev}.cvd_50)"
    if indicator == 'ema_spread_roc':
        # spread_pct = ((ema_9 - ema_21) / ema_21) * 100
        cur = f"(({alias_cur}.ema_9 - {alias_cur}.ema_21) / nullif({alias_cur}.ema_21, 0.0)) * 100.0"
        prev = f"(({alias_prev}.ema_9 - {alias_prev}.ema_21) / nullif({alias_prev}.ema_21, 0.0)) * 100.0"
        return f"({cur} - {prev})"
    raise ValueError(f'unknown indicator: {indicator}')


def build_sql(v: Variant) -> str:
    sigmas_values = _values_sigmas()

    # Common event definition.
    # We compute features at t_feat = t0 - 15m (last completed candle before event).
    # Feature uses two rows from training.spot_15m_indicators at t_feat and (t_feat - lookback).
    feature_expr = _feature_expr(v.indicator, 'cur', 'prev')

    if v.normalization == 'global':
        return f"""
with
params as (
  select
    'BTC'::text as symbol,
    interval '{v.lookback_min} minutes' as lb
),

-- events to predict: 15m starts at :00/:15/:30/:45
candles as (
  select
    c.open_time as t0,
    case
      when c.close > c.open then 1
      when c.close < c.open then 0
      else null
    end as outcome_up
  from training.spot_15m c
  where c.symbol = (select symbol from params)
    and extract(second from c.open_time) = 0
    and extract(minute from c.open_time) in (0,15,30,45)
    and c.open is not null and c.close is not null
),

base as (
  select
    e.t0,
    e.outcome_up,
    (e.t0 - interval '15 minutes') as t_feat
  from candles e
  where e.outcome_up is not null
),

feat as (
  select
    b.t0,
    b.outcome_up,
    {feature_expr}::float8 as x
  from base b
  join training.spot_15m_indicators cur
    on cur.symbol = (select symbol from params)
   and cur.open_time = b.t_feat
  join training.spot_15m_indicators prev
    on prev.symbol = (select symbol from params)
   and prev.open_time = b.t_feat - (select lb from params)
  where {feature_expr} is not null
),

stats as (
  select
    avg(x)::float8 as mu,
    stddev_samp(x)::float8 as sd,
    count(*)::bigint as n_eligible
  from feat
),

sigmas as (
  select * from (values {sigmas_values}) v(k)
)

select
  '{v.slug}'::text as variant,
  '{v.indicator}'::text as indicator,
  '{v.normalization}'::text as normalization,
  {v.lookback_min}::int as lookback_min,
  null::int as rolling_days,
  null::int as rolling_min_n,
  s.n_eligible,
  side,
  k as sigma,
  n_pred,
  round((100.0*n_pred/nullif(s.n_eligible,0))::numeric, 6)::float8 as coverage_pct,
  accuracy_pct
from (
  select
    'UP'::text as side,
    k,
    count(*) filter (where f.x > st.mu + k*st.sd)::bigint as n_pred,
    round((100.0*avg(f.outcome_up::float8) filter (where f.x > st.mu + k*st.sd))::numeric, 4)::float8 as accuracy_pct
  from feat f
  cross join stats st
  cross join sigmas
  group by k

  union all

  select
    'DOWN'::text as side,
    k,
    count(*) filter (where f.x < st.mu - k*st.sd)::bigint as n_pred,
    round((100.0*avg((1 - f.outcome_up)::float8) filter (where f.x < st.mu - k*st.sd))::numeric, 4)::float8 as accuracy_pct
  from feat f
  cross join stats st
  cross join sigmas
  group by k
) q
cross join stats s
order by side, sigma;
"""

    if v.normalization == 'rolling':
        assert v.rolling_days is not None
        assert v.rolling_min_n is not None
        return f"""
with
params as (
  select
    'BTC'::text as symbol,
    interval '{v.lookback_min} minutes' as lb,
    interval '{v.rolling_days} days' as win
),

candles as (
  select
    c.open_time as t0,
    case
      when c.close > c.open then 1
      when c.close < c.open then 0
      else null
    end as outcome_up
  from training.spot_15m c
  where c.symbol = (select symbol from params)
    and extract(second from c.open_time) = 0
    and extract(minute from c.open_time) in (0,15,30,45)
    and c.open is not null and c.close is not null
),

base as (
  select
    e.t0,
    e.outcome_up,
    (e.t0 - interval '15 minutes') as t_feat
  from candles e
  where e.outcome_up is not null
),

feat as (
  select
    b.t0,
    b.outcome_up,
    {feature_expr}::float8 as x
  from base b
  join training.spot_15m_indicators cur
    on cur.symbol = (select symbol from params)
   and cur.open_time = b.t_feat
  join training.spot_15m_indicators prev
    on prev.symbol = (select symbol from params)
   and prev.open_time = b.t_feat - (select lb from params)
  where {feature_expr} is not null
),

roll as (
  select
    f.*,
    avg(x) over w as mu,
    stddev_samp(x) over w as sd,
    count(*) over w as n_win
  from feat f
  window w as (
    order by t0
    range between (select win from params) preceding and interval '1 microsecond' preceding
  )
),

eligible as (
  select *
  from roll
  where sd is not null and sd > 0
    and n_win >= {v.rolling_min_n}
),

sigmas as (
  select * from (values {sigmas_values}) v(k)
),

meta as (
  select count(*)::bigint as n_eligible
  from eligible
)

select
  '{v.slug}'::text as variant,
  '{v.indicator}'::text as indicator,
  '{v.normalization}'::text as normalization,
  {v.lookback_min}::int as lookback_min,
  {v.rolling_days}::int as rolling_days,
  {v.rolling_min_n}::int as rolling_min_n,
  m.n_eligible,
  side,
  k as sigma,
  n_pred,
  round((100.0*n_pred/nullif(m.n_eligible,0))::numeric, 6)::float8 as coverage_pct,
  accuracy_pct
from (
  select
    'UP'::text as side,
    k,
    count(*) filter (where e.x > e.mu + k*e.sd)::bigint as n_pred,
    round((100.0*avg(e.outcome_up::float8) filter (where e.x > e.mu + k*e.sd))::numeric, 4)::float8 as accuracy_pct
  from eligible e
  cross join sigmas
  group by k

  union all

  select
    'DOWN'::text as side,
    k,
    count(*) filter (where e.x < e.mu - k*e.sd)::bigint as n_pred,
    round((100.0*avg((1 - e.outcome_up)::float8) filter (where e.x < e.mu - k*e.sd))::numeric, 4)::float8 as accuracy_pct
  from eligible e
  cross join sigmas
  group by k
) q
cross join meta m
order by side, sigma;
"""

    raise ValueError('normalization must be global or rolling')


def write_variant_report(out_dir: Path, rows: list[dict[str, str]]) -> None:
    # rows are already sorted by side/sigma.
    # Find best operating points >=70% accuracy with coverage >=0.5%.
    best = []
    for r in rows:
        acc = float(r['accuracy_pct']) if r['accuracy_pct'] else float('nan')
        cov = float(r['coverage_pct']) if r['coverage_pct'] else 0.0
        n_pred = int(r['n_pred'])
        if n_pred <= 0:
            continue
        if acc >= 70.0 and cov >= 0.5:
            best.append((acc, cov, r['side'], float(r['sigma']), n_pred))

    best.sort(reverse=True)

    any_signal = any(int(r['n_pred']) > 0 for r in rows)
    any_70 = len(best) > 0

    head = rows[0]
    md = []
    md.append(f"# Variant: {head['variant']}")
    md.append('')
    md.append(f"indicator: `{head['indicator']}`")
    md.append(f"normalization: `{head['normalization']}`")
    md.append(f"lookback_min: `{head['lookback_min']}`")
    md.append(f"rolling_days: `{head['rolling_days']}`")
    md.append(f"rolling_min_n: `{head['rolling_min_n']}`")
    md.append(f"n_eligible: `{head['n_eligible']}`")
    md.append('')

    if not any_signal:
        md.append('No triggers at any sigma (n_pred=0 for all).')
    elif not any_70:
        md.append('No operating point met the >=70% accuracy and >=0.5% coverage gate in training.')
    else:
        md.append('Operating points (training) with accuracy>=70% and coverage>=0.5%:')
        for acc, cov, side, sigma, n_pred in best[:10]:
            md.append(f"- {side} @ {sigma}σ: accuracy={acc:.4f}% coverage={cov:.6f}% n_pred={n_pred}")

    md.append('')
    md.append('Full sweep:')
    md.append('')
    md.append('side | sigma | n_pred | coverage_pct | accuracy_pct')
    md.append('---|---:|---:|---:|---:')
    for r in rows:
        md.append(f"{r['side']} | {r['sigma']} | {r['n_pred']} | {r['coverage_pct']} | {r['accuracy_pct']}")

    (out_dir / 'REPORT.md').write_text('\n'.join(md) + '\n')


def run_one(db_url: str, out_root: Path, v: Variant) -> str:
    out_dir = out_root / v.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    sql = build_sql(v)
    (out_dir / 'query.sql').write_text(sql + '\n')

    out_csv = out_dir / 'results.csv'
    _psql_copy(db_url, sql, out_csv)

    rows = list(csv.DictReader(out_csv.open()))
    write_variant_report(out_dir, rows)

    return v.slug


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=min(8, (os.cpu_count() or 8)))
    ap.add_argument('--rolling-days', type=int, default=21)
    ap.add_argument('--rolling-min-n', default='500,1000')
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    db_url = _load_db_url(root / '.env')

    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_root = root / 'scripts' / 'output' / 'indicator_sigma_sweeps' / run_id
    out_root.mkdir(parents=True, exist_ok=True)

    rolling_min_ns = [int(x.strip()) for x in args.rolling_min_n.split(',') if x.strip()]

    variants: list[Variant] = []

    def add(indicator: str, lookback: int, normalization: str, min_n: int | None = None):
        slug = f"{indicator}__lb{lookback}m__{normalization}"
        if normalization == 'rolling':
            slug += f"__win{args.rolling_days}d__minn{min_n}"
        variants.append(
            Variant(
                slug=slug,
                indicator=indicator,
                lookback_min=lookback,
                normalization=normalization,
                rolling_days=args.rolling_days if normalization == 'rolling' else None,
                rolling_min_n=min_n if normalization == 'rolling' else None,
            )
        )

    # CVD ROC (15m grid)
    for lb in (15, 60):
        add('cvd_50_roc', lb, 'global')
        for min_n in rolling_min_ns:
            add('cvd_50_roc', lb, 'rolling', min_n=min_n)

    # EMA spread ROC (15m grid)
    for lb in (15, 60):
        add('ema_spread_roc', lb, 'global')
        for min_n in rolling_min_ns:
            add('ema_spread_roc', lb, 'rolling', min_n=min_n)

    # Run in parallel
    meta = {
        'run_id': run_id,
        'out_root': str(out_root),
        'jobs': args.jobs,
        'rolling_days': args.rolling_days,
        'rolling_min_n': rolling_min_ns,
        'sigmas': SIGMAS,
        'indicator_notes': {
            'cvd_50_roc': 'x = cvd_50(t_feat) - cvd_50(t_feat - lookback), with t_feat=t0-15m',
            'ema_spread_roc': 'spread_pct = ((ema9-ema21)/ema21)*100; x = spread_pct(t_feat)-spread_pct(t_feat-lookback)',
        },
    }
    (out_root / 'run.json').write_text(json.dumps(meta, indent=2) + '\n')

    errors = []
    with ProcessPoolExecutor(max_workers=int(args.jobs)) as ex:
        futs = [ex.submit(run_one, db_url, out_root, v) for v in variants]
        for fut in as_completed(futs):
            try:
                _ = fut.result()
            except Exception as e:
                errors.append(str(e))

    if errors:
        (out_root / 'errors.txt').write_text('\n'.join(errors) + '\n')
        raise SystemExit(f"{len(errors)} variant(s) failed; see {out_root/'errors.txt'}")

    # Build a top-level summary file.
    summary_lines = []
    summary_lines.append('# Indicator Sigma Sweeps (Training Schema)')
    summary_lines.append('')
    summary_lines.append(f"Run: `{out_root}`")
    summary_lines.append('')
    summary_lines.append('Variants:')
    for v in sorted(variants, key=lambda x: x.slug):
        summary_lines.append(f"- `{v.slug}`")
    summary_lines.append('')
    summary_lines.append('Per-variant reports live under each variant folder as `REPORT.md`.')
    (out_root / 'REPORT.md').write_text('\n'.join(summary_lines) + '\n')


if __name__ == '__main__':
    main()
