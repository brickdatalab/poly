#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine import build_db_url, load_env, psql_json, table

START_UTC = "2026-01-23 00:00:00+00"
PAIRS = ["BTC-USD", "ETH-USD"]


def run_backtest(db_url: str) -> dict:
    sql = f"""
    with base as (
      select s.pair, s.bucket_time,
        max(v1::float8) filter (where config_id='syn_rsi_velocity_5m_3bar_z20') as rsi_v,
        max(v1::float8) filter (where config_id='syn_early_momentum_divergence_tplus1') as emd,
        max(v1::float8) filter (where config_id='syn_oi_funding_impulse_tplus2') as oii,
        case when o.close>o.open then 1 when o.close<o.open then 0 else null end as outcome_up
      from indicators.synthetic_indicator_values s
      join indicators.ohlcv_15m o using(pair,bucket_time)
      where s.bucket_time >= '{START_UTC}'
        and s.pair in ('BTC-USD','ETH-USD')
        and s.config_id in ('syn_rsi_velocity_5m_3bar_z20','syn_early_momentum_divergence_tplus1','syn_oi_funding_impulse_tplus2')
      group by s.pair,s.bucket_time,o.open,o.close
    ), thresholds as (
      select
        percentile_disc(0.70) within group (order by emd) filter (where pair='BTC-USD') as btc_emd_q70,
        percentile_disc(0.94) within group (order by oii) filter (where pair='BTC-USD') as btc_oii_q94,
        percentile_disc(0.85) within group (order by rsi_v) filter (where pair='ETH-USD') as eth_rsi_q85,
        percentile_disc(0.15) within group (order by emd) filter (where pair='ETH-USD') as eth_emd_q15
      from base
    ), eval as (
      select b.*, t.*,
        case
          when b.pair='BTC-USD' and b.emd >= t.btc_emd_q70 and b.oii >= t.btc_oii_q94 then 'down'
          when b.pair='ETH-USD' and b.rsi_v >= t.eth_rsi_q85 and b.emd <= t.eth_emd_q15 then 'up'
          else 'none'
        end as prediction
      from base b
      cross join thresholds t
      where b.outcome_up is not null
    ), metrics as (
      select
        pair,
        count(*) filter (where prediction <> 'none')::int as triggered,
        sum(case
              when prediction='up' and outcome_up=1 then 1
              when prediction='down' and outcome_up=0 then 1
              else 0
            end) filter (where prediction <> 'none')::int as correct,
        round((100.0 * avg(case
                             when prediction='up' and outcome_up=1 then 1.0
                             when prediction='down' and outcome_up=0 then 1.0
                             else 0.0
                           end) filter (where prediction <> 'none'))::numeric, 4)::float8 as accuracy_pct,
        sum((prediction='up')::int)::int as up_triggers,
        sum((prediction='down')::int)::int as down_triggers,
        count(*)::int as events_evaluated
      from eval
      group by pair
      union all
      select
        'COMBINED'::text as pair,
        count(*) filter (where prediction <> 'none')::int as triggered,
        sum(case
              when prediction='up' and outcome_up=1 then 1
              when prediction='down' and outcome_up=0 then 1
              else 0
            end) filter (where prediction <> 'none')::int as correct,
        round((100.0 * avg(case
                             when prediction='up' and outcome_up=1 then 1.0
                             when prediction='down' and outcome_up=0 then 1.0
                             else 0.0
                           end) filter (where prediction <> 'none'))::numeric, 4)::float8 as accuracy_pct,
        sum((prediction='up')::int)::int as up_triggers,
        sum((prediction='down')::int)::int as down_triggers,
        count(*)::int as events_evaluated
      from eval
    )
    select json_build_object(
      'thresholds', (select row_to_json(t) from thresholds t),
      'metrics', (select json_agg(m order by case when m.pair='COMBINED' then 2 else 1 end, m.pair) from metrics m)
    ) as payload
    """
    rows = psql_json(db_url, sql)
    if not rows:
        raise SystemExit("No backtest rows returned")
    return rows[0]["payload"]


def write_outputs(payload: dict) -> Path:
    now = datetime.now(timezone.utc)
    out_dir = Path(__file__).resolve().parents[1] / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"codex_backtest_{now.strftime('%Y%m%dT%H%M%SZ')}"

    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"

    json_path.write_text(json.dumps(payload, indent=2))

    thr = payload.get("thresholds") or {}
    metrics = payload.get("metrics") or []
    rows = []
    for r in metrics:
        rows.append([
            r.get("pair"),
            r.get("triggered"),
            r.get("correct"),
            r.get("accuracy_pct"),
            r.get("up_triggers"),
            r.get("down_triggers"),
            r.get("events_evaluated"),
        ])

    md = []
    md.append("# CODEX Backtest")
    md.append("")
    md.append(f"- Start UTC: `{START_UTC}`")
    md.append(f"- Pairs: `{', '.join(PAIRS)}`")
    md.append("")
    md.append("## Thresholds")
    md.append(f"- BTC EMD q70: `{thr.get('btc_emd_q70')}`")
    md.append(f"- BTC OII q94: `{thr.get('btc_oii_q94')}`")
    md.append(f"- ETH RSI q85: `{thr.get('eth_rsi_q85')}`")
    md.append(f"- ETH EMD q15: `{thr.get('eth_emd_q15')}`")
    md.append("")
    md.append("## Metrics")
    md.append("```text")
    md.append(table(["pair", "triggered", "correct", "accuracy_pct", "up_triggers", "down_triggers", "events_evaluated"], rows))
    md.append("```")
    md_path.write_text("\n".join(md) + "\n")

    return json_path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)
    payload = run_backtest(db_url)
    out_json = write_outputs(payload)

    print(f"output_json={out_json}")
    print()

    metrics = payload.get("metrics") or []
    rows = [
        [
            r.get("pair"),
            r.get("triggered"),
            r.get("correct"),
            r.get("accuracy_pct"),
            r.get("up_triggers"),
            r.get("down_triggers"),
            r.get("events_evaluated"),
        ]
        for r in metrics
    ]
    print(table(["pair", "triggered", "correct", "accuracy_pct", "up_triggers", "down_triggers", "events_evaluated"], rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
