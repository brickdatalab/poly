#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone


def load_db_url(env_path: Path) -> str:
    if not env_path.exists():
        raise SystemExit(f"Missing {env_path}")
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get('SUPABASE_DB_URL')
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_json(db_url: str, sql: str) -> dict:
    # We ask Postgres to return a single JSON value (as text) and parse it.
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
    out = subprocess.check_output(cmd, text=True)
    out = out.strip()
    if not out:
        raise RuntimeError("Empty JSON output from psql")
    return json.loads(out)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root / ".env")

    pair = "ETH-USD"
    target_time_utc = "2026-02-10T19:00:00Z"  # 14:00 EST on 2026-02-10

    # NOTE: Keep this as one DB round-trip for speed and to reduce local stitching errors.
    sql = f"""
with
one_m_src as (
  select *
  from indicators.ohlcv_1m
  where pair = '{pair}'
  order by bucket_time desc
  limit 100
),
one_m as (
  select
    jsonb_agg(
      jsonb_build_object(
        'bucket_time', bucket_time,
        'open', open::float8,
        'high', high::float8,
        'low', low::float8,
        'close', close::float8,
        'volume', volume::float8,
        'buy_volume', buy_volume::float8,
        'sell_volume', sell_volume::float8,
        'trade_count', trade_count
      )
      order by bucket_time
    ) as rows,
    (select close::float8 from one_m_src order by bucket_time desc limit 1) as latest_close
  from one_m_src
),

fifteen_m_src as (
  select *
  from indicators.ohlcv_15m
  where pair = '{pair}'
    and bucket_time >= (now() - interval '6 hours')
  order by bucket_time desc
  limit 24
),
fifteen_m as (
  select
    jsonb_agg(
      jsonb_build_object(
        'bucket_time', bucket_time,
        'open', open::float8,
        'high', high::float8,
        'low', low::float8,
        'close', close::float8,
        'volume', volume::float8
      )
      order by bucket_time
    ) as rows,
    (select open::float8 from fifteen_m_src order by bucket_time asc limit 1) as first_open,
    (select close::float8 from fifteen_m_src order by bucket_time desc limit 1) as last_close
  from fifteen_m_src
),

momentum as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'config_id', config_id,
        'indicator_name', indicator_name,
        'timeframe', timeframe,
        'v1', v1,
        'v2', v2,
        'v3', v3
      )
      order by indicator_name, timeframe, config_id
    ),
    '[]'::jsonb
  ) as rows
  from (
    select distinct on (c.config_id)
      c.config_id,
      c.indicator_name,
      c.timeframe,
      iv.v1::float8 as v1,
      iv.v2::float8 as v2,
      iv.v3::float8 as v3
    from indicators.indicator_configs c
    join indicators.indicator_values iv
      on iv.config_id = c.config_id
    where c.is_active = true
      and c.indicator_name in ('rsi','macd','stochastic')
      and c.timeframe in ('1m','5m','15m')
      and iv.pair = '{pair}'
      and iv.bucket_time >= (now() - interval '7 days')
    order by c.config_id, iv.bucket_time desc
  ) t
),

volatility as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'config_id', config_id,
        'indicator_name', indicator_name,
        'timeframe', timeframe,
        'v1', v1,
        'v2', v2
      )
      order by indicator_name, timeframe, config_id
    ),
    '[]'::jsonb
  ) as rows
  from (
    select distinct on (c.config_id)
      c.config_id,
      c.indicator_name,
      c.timeframe,
      iv.v1::float8 as v1,
      iv.v2::float8 as v2
    from indicators.indicator_configs c
    join indicators.indicator_values iv
      on iv.config_id = c.config_id
    where c.is_active = true
      and c.indicator_name in ('bollinger','atr')
      and c.timeframe in ('1m','5m','15m')
      and iv.pair = '{pair}'
      and iv.bucket_time >= (now() - interval '7 days')
    order by c.config_id, iv.bucket_time desc
  ) t
),

trend as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'config_id', config_id,
        'indicator_name', indicator_name,
        'timeframe', timeframe,
        'v1', v1,
        'v2', v2
      )
      order by indicator_name, timeframe, config_id
    ),
    '[]'::jsonb
  ) as rows
  from (
    select distinct on (c.config_id)
      c.config_id,
      c.indicator_name,
      c.timeframe,
      iv.v1::float8 as v1,
      null::float8 as v2
    from indicators.indicator_configs c
    join indicators.indicator_values iv
      on iv.config_id = c.config_id
    where c.is_active = true
      and c.indicator_name in ('ema','sma','wma','vwma','hma','vwap')
      and c.timeframe in ('1m','5m','15m')
      and iv.pair = '{pair}'
      and iv.bucket_time >= (now() - interval '7 days')
    order by c.config_id, iv.bucket_time desc
  ) t
),

open_interest_src as (
  select *
  from indicators.open_interest
  where pair = '{pair}'
  order by bucket_time desc
  limit 50
),
open_interest_rows as (
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'bucket_time', bucket_time,
        'open_interest', open_interest,
        'oi_change', oi_change,
        'oi_change_pct', oi_change_pct,
        'close_price', close_price,
        'volume', volume,
        'price_change_pct', price_change_pct,
        'oi_volume_ratio', oi_volume_ratio,
        'oi_divergence', oi_divergence,
        'weak_rally', weak_rally,
        'weak_selloff', weak_selloff,
        'funding_rate', funding_rate,
        'funding_rate_8h_avg', funding_rate_8h_avg
      )
      order by bucket_time
    ),
    '[]'::jsonb
  ) as rows,
  (select open_interest from open_interest_src order by bucket_time desc limit 1) as current_oi,
  (select open_interest from open_interest_src order by bucket_time desc offset 4 limit 1) as oi_1h_ago
  from open_interest_src
),

open_interest_obj as (
  select
    jsonb_build_object(
      'latest_rows', rows,
      'current_oi', coalesce(current_oi, 0)::float8,
      'oi_trend_1h', (
        case
          when current_oi is null or oi_1h_ago is null then 'stable'
          when (current_oi - oi_1h_ago) > (0.001 * greatest(abs(current_oi), 1)) then 'increasing'
          when (current_oi - oi_1h_ago) < (-0.001 * greatest(abs(current_oi), 1)) then 'decreasing'
          else 'stable'
        end
      )
    ) as obj
  from open_interest_rows
),

oi_features_src as (
  select *
  from indicators.oi_features
  where pair = '{pair}'
  order by bucket_time desc
  limit 20
),
oi_features_obj as (
  select jsonb_build_object(
    'latest_features',
    coalesce(
      jsonb_agg(
        jsonb_build_object(
          'bucket_time', bucket_time,
          'weak_rally_streak', weak_rally_streak,
          'weak_selloff_streak', weak_selloff_streak,
          'funding_oi_pressure', funding_oi_pressure,
          'funding_oi_pressure_1h', funding_oi_pressure_1h,
          'oi_roc_1h', oi_roc_1h,
          'oi_roc_4h', oi_roc_4h,
          'oi_roc_24h', oi_roc_24h,
          'oi_acceleration', oi_acceleration,
          'turnover_1h', turnover_1h,
          'turnover_4h', turnover_4h,
          'price_oi_corr_16', price_oi_corr_16,
          'price_oi_corr_24', price_oi_corr_24,
          'oi_change_vol_pctile_24h', oi_change_vol_pctile_24h
        )
        order by bucket_time
      ),
      '[]'::jsonb
    )
  ) as obj
  from oi_features_src
),

order_book_src as (
  select *
  from indicators.order_book_indicators
  where pair = '{pair}'
  order by captured_at desc
  limit 30
),
order_book_rows as (
  select
    coalesce(
      jsonb_agg(
        jsonb_build_object(
          'captured_at', captured_at,
          'depth_ratio', depth_ratio::float8,
          'imbalance', imbalance::float8,
          'spread_pct', spread_pct::float8,
          'mid_price', mid_price::float8,
          'bid_depth_10bps', bid_depth_10bps::float8,
          'ask_depth_10bps', ask_depth_10bps::float8,
          'bid_depth_25bps', bid_depth_25bps::float8,
          'ask_depth_25bps', ask_depth_25bps::float8,
          'bid_depth_50bps', bid_depth_50bps::float8,
          'ask_depth_50bps', ask_depth_50bps::float8,
          'slippage_buy_100', slippage_buy_100::float8,
          'slippage_sell_100', slippage_sell_100::float8
        )
        order by captured_at
      ),
      '[]'::jsonb
    ) as rows,
    (select mid_price::float8 from order_book_src order by captured_at desc limit 1) as current_mid_price,
    (select imbalance::float8 from order_book_src order by captured_at desc limit 1) as current_imbalance
  from order_book_src
),
order_book_obj as (
  select jsonb_build_object(
    'latest_snapshots', rows,
    'current_mid_price', coalesce(current_mid_price, 0)::float8,
    'liquidity_imbalance', (
      case
        when current_imbalance is null then 'balanced'
        when current_imbalance > 0.10 then 'bid_dominant'
        when current_imbalance < -0.10 then 'ask_dominant'
        else 'balanced'
      end
    )
  ) as obj
  from order_book_rows
)

select (
  jsonb_build_object(
    'timestamp_utc', now(),
    'target_time_utc', '{target_time_utc}',
    'pair', '{pair}',

    'ohlcv_data', jsonb_build_object(
      'timeframes', jsonb_build_object(
        '1m', coalesce((select rows from one_m), '[]'::jsonb),
        '15m', coalesce((select rows from fifteen_m), '[]'::jsonb)
      ),
      'latest_close', coalesce((select latest_close from one_m), 0)::float8,
      'current_trend', (
        case
          when (select first_open from fifteen_m) is null or (select last_close from fifteen_m) is null then 'neutral'
          when abs(((select last_close from fifteen_m) - (select first_open from fifteen_m)) / nullif((select first_open from fifteen_m), 0)) < 0.001 then 'neutral'
          when ((select last_close from fifteen_m) - (select first_open from fifteen_m)) > 0 then 'bullish'
          else 'bearish'
        end
      )
    ),

    'technical_indicators', jsonb_build_object(
      'momentum', (select rows from momentum),
      'volatility', (select rows from volatility),
      'trend', (select rows from trend)
    ),

    'open_interest', (select obj from open_interest_obj),
    'oi_features', (select obj from oi_features_obj),
    'order_book_indicators', (select obj from order_book_obj)
  )
)::text;
"""

    data = psql_json(db_url, sql)

    # Ensure required top-level fields exist even if DB returned null arrays.
    data.setdefault("timestamp_utc", datetime.now(timezone.utc).isoformat())
    data.setdefault("target_time_utc", target_time_utc)
    data.setdefault("pair", pair)

    out_path = root / "response.json"
    out_path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")


if __name__ == "__main__":
    main()
