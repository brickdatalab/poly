-- Canonical synthetic signal dataset (indicators schema).
-- Replace :START_TS, :END_TS, :PAIR_LIST when running manually.

with labels as (
  select
    o.pair,
    o.bucket_time,
    o.open::float8 as event_open,
    o.close::float8 as event_close,
    ((o.close - o.open) / nullif(o.open, 0))::float8 as event_return,
    case
      when o.close > o.open then 'up'
      when o.close < o.open then 'down'
      else 'flat'
    end as outcome
  from indicators.ohlcv_15m o
  where o.pair in (:PAIR_LIST)
    and o.bucket_time >= :START_TS::timestamptz
    and o.bucket_time <= :END_TS::timestamptz
    and extract(second from o.bucket_time) = 0
    and extract(minute from o.bucket_time)::int in (0, 15, 30, 45)
)
select
  s.pair,
  s.bucket_time,
  s.config_id,
  c.decision_phase,
  s.v1::float8 as value,
  s.v2::float8,
  s.v3::float8,
  s.v4::float8,
  s.v5::float8,
  s.source_time,
  s.computed_at,
  l.event_open,
  l.event_close,
  l.event_return,
  l.outcome,
  atr.v1::float8 as atr_14_15m,
  ema9.v1::float8 as ema_9_15m,
  ema21.v1::float8 as ema_21_15m,
  ob.spread_pct::float8 as spread_pct,
  ob.imbalance::float8 as imbalance,
  oif.funding_oi_pressure::float8 as funding_oi_pressure,
  oif.oi_acceleration::float8 as oi_acceleration
from indicators.synthetic_indicator_values s
join indicators.synthetic_indicator_configs c
  on c.config_id = s.config_id
join labels l
  on l.pair = s.pair
 and l.bucket_time = s.bucket_time
left join indicators.indicator_values atr
  on atr.pair = s.pair and atr.bucket_time = s.bucket_time and atr.config_id = 'atr_14_15m'
left join indicators.indicator_values ema9
  on ema9.pair = s.pair and ema9.bucket_time = s.bucket_time and ema9.config_id = 'ema_9_15m'
left join indicators.indicator_values ema21
  on ema21.pair = s.pair and ema21.bucket_time = s.bucket_time and ema21.config_id = 'ema_21_15m'
left join lateral (
  select ob1.spread_pct, ob1.imbalance
  from indicators.order_book_indicators ob1
  where ob1.pair = s.pair
    and ob1.captured_at <= s.bucket_time + interval '2 minutes'
  order by ob1.captured_at desc
  limit 1
) ob on true
left join indicators.oi_features oif
  on oif.pair = s.pair and oif.bucket_time = s.bucket_time
where c.is_active
  and s.pair in (:PAIR_LIST)
  and l.outcome in ('up','down')
  and s.v1 is not null
order by s.pair, s.config_id, s.bucket_time;
