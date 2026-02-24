-- Regime feature projection for canonical dataset rows.
-- Works after materializing canonical rows into a temp table/view named :DATASET_TABLE.

select
  pair,
  bucket_time,
  config_id,
  value,
  outcome,
  (atr_14_15m / nullif(event_close, 0))::float8 as atr_pct,
  (abs(ema_9_15m - ema_21_15m) / nullif(event_close, 0))::float8 as trend_strength,
  abs(spread_pct)::float8 as liq_spread,
  abs(funding_oi_pressure)::float8 as oi_pressure_abs
from :DATASET_TABLE;
