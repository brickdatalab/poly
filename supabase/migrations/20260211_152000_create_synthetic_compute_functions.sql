-- Compute functions for six synthetic indicators.

create or replace function indicators.fn_syn_iv_value(
  p_pair text,
  p_bucket_time timestamptz,
  p_config_id text,
  p_col text default 'v1',
  p_exact boolean default false
)
returns numeric
language plpgsql
as $$
declare
  v_out numeric;
begin
  if p_col not in ('v1', 'v2', 'v3', 'v4', 'v5') then
    raise exception 'Unsupported indicator value column: %', p_col;
  end if;

  if p_exact then
    execute format(
      'select %I from indicators.indicator_values where pair = $1 and config_id = $2 and bucket_time = $3',
      p_col
    )
    into v_out
    using p_pair, p_config_id, p_bucket_time;
  else
    execute format(
      'select %I from indicators.indicator_values where pair = $1 and config_id = $2 and bucket_time <= $3 order by bucket_time desc limit 1',
      p_col
    )
    into v_out
    using p_pair, p_config_id, p_bucket_time;
  end if;

  return v_out;
end;
$$;

comment on function indicators.fn_syn_iv_value(text,timestamptz,text,text,boolean) is
  'Helper: fetches v1..v5 from indicators.indicator_values for a config at exact or latest<=bucket.';

create or replace function indicators.fn_syn_upsert_value(
  p_pair text,
  p_bucket_time timestamptz,
  p_config_id text,
  p_v1 numeric,
  p_v2 numeric,
  p_v3 numeric,
  p_v4 numeric,
  p_v5 numeric,
  p_source_time timestamptz,
  p_quality_flags jsonb
)
returns void
language plpgsql
as $$
begin
  insert into indicators.synthetic_indicator_values (
    pair, bucket_time, config_id, v1, v2, v3, v4, v5, source_time, computed_at, quality_flags
  )
  values (
    p_pair, p_bucket_time, p_config_id, p_v1, p_v2, p_v3, p_v4, p_v5, p_source_time, now(), p_quality_flags
  )
  on conflict (pair, bucket_time, config_id)
  do update
    set v1 = excluded.v1,
        v2 = excluded.v2,
        v3 = excluded.v3,
        v4 = excluded.v4,
        v5 = excluded.v5,
        source_time = excluded.source_time,
        computed_at = excluded.computed_at,
        quality_flags = excluded.quality_flags;
end;
$$;

comment on function indicators.fn_syn_upsert_value(text,timestamptz,text,numeric,numeric,numeric,numeric,numeric,timestamptz,jsonb) is
  'Helper: idempotent upsert into indicators.synthetic_indicator_values.';

create or replace function indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  v_n5 int;
  v_n15 int;
  v_num5 numeric;
  v_num15 numeric;
  v_den5 numeric;
  v_den15 numeric;
  v_er5 numeric;
  v_er15 numeric;
  v_signal numeric;
  v_src5 timestamptz;
  v_src15 timestamptz;
  v_q jsonb;
begin
  with s as (
    select bucket_time, close::numeric as c
    from indicators.ohlcv_5m
    where pair = p_pair and bucket_time <= p_bucket_time
    order by bucket_time desc
    limit 12
  ), o as (
    select bucket_time, c, row_number() over (order by bucket_time) as rn
    from s
  ), d as (
    select c, lag(c) over (order by rn) as prev_c
    from o
  )
  select
    (select count(*) from o),
    (select c from o order by rn desc limit 1) - (select c from o order by rn asc limit 1),
    (select sum(abs(c - prev_c)) from d where prev_c is not null),
    (select max(bucket_time) from o)
  into v_n5, v_num5, v_den5, v_src5;

  with s as (
    select bucket_time, close::numeric as c
    from indicators.ohlcv_15m
    where pair = p_pair and bucket_time <= p_bucket_time
    order by bucket_time desc
    limit 8
  ), o as (
    select bucket_time, c, row_number() over (order by bucket_time) as rn
    from s
  ), d as (
    select c, lag(c) over (order by rn) as prev_c
    from o
  )
  select
    (select count(*) from o),
    (select c from o order by rn desc limit 1) - (select c from o order by rn asc limit 1),
    (select sum(abs(c - prev_c)) from d where prev_c is not null),
    (select max(bucket_time) from o)
  into v_n15, v_num15, v_den15, v_src15;

  v_er5 := case when coalesce(v_n5,0) >= 12 and coalesce(v_den5,0) <> 0 then v_num5 / v_den5 else null end;
  v_er15 := case when coalesce(v_n15,0) >= 8 and coalesce(v_den15,0) <> 0 then v_num15 / v_den15 else null end;
  v_signal := case when v_er5 is not null and v_er15 is not null then v_er5 * v_er15 else null end;

  v_q := jsonb_build_object(
    'missing_5m_history', coalesce(v_n5,0) < 12,
    'missing_15m_history', coalesce(v_n15,0) < 8,
    'zero_path_5m', coalesce(v_den5,0) = 0,
    'zero_path_15m', coalesce(v_den15,0) = 0
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_mtf_signed_efficiency_ratio_5m12_15m8',
    v_signal,
    v_er5,
    v_er15,
    abs(v_er5),
    abs(v_er15),
    greatest(v_src5, v_src15),
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio(text,timestamptz) is
  'Computes product of 5m(12) and 15m(8) signed efficiency ratios at event boundary.';

create or replace function indicators.fn_compute_synthetic_rsi_velocity_5m(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  v_raw numeric;
  v_mu numeric;
  v_sd numeric;
  v_sd_used numeric;
  v_z numeric;
  v_rsi5_last numeric;
  v_rsi1h_last numeric;
  v_src5 timestamptz;
  v_src1h timestamptz;
  v_q jsonb;
begin
  with s as (
    select bucket_time, v1::numeric as rsi
    from indicators.indicator_values
    where pair = p_pair and config_id = 'rsi_7_5m' and bucket_time <= p_bucket_time
    order by bucket_time desc
    limit 30
  ), o as (
    select bucket_time, rsi, row_number() over (order by bucket_time) as rn_asc
    from s
  ), d as (
    select
      rn_asc,
      rsi,
      rsi - lag(rsi, 3) over (order by rn_asc) as diff3
    from o
  )
  select
    (select rsi from o order by rn_asc desc limit 1) - (select rsi from o order by rn_asc desc offset 3 limit 1),
    (select avg(diff3) from d where diff3 is not null),
    (select stddev_samp(diff3) from d where diff3 is not null),
    (select rsi from o order by rn_asc desc limit 1),
    (select max(bucket_time) from o)
  into v_raw, v_mu, v_sd, v_rsi5_last, v_src5;

  select bucket_time, v1::numeric
  into v_src1h, v_rsi1h_last
  from indicators.indicator_values
  where pair = p_pair and config_id = 'rsi_14_1h' and bucket_time <= p_bucket_time
  order by bucket_time desc
  limit 1;

  v_sd_used := greatest(coalesce(v_sd, 0), 0.5);
  v_z := case when v_raw is not null and v_mu is not null then (v_raw - v_mu) / v_sd_used else null end;

  v_q := jsonb_build_object(
    'missing_rsi_7_5m', v_rsi5_last is null,
    'missing_rsi_14_1h', v_rsi1h_last is null,
    'std_floor_applied', coalesce(v_sd,0) < 0.5
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_rsi_velocity_5m_3bar_z20',
    v_z,
    v_raw,
    v_rsi5_last,
    v_rsi1h_last,
    v_sd_used,
    greatest(v_src5, v_src1h),
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_rsi_velocity_5m(text,timestamptz) is
  'Computes z-scored 5m RSI velocity and includes hourly RSI context.';

create or replace function indicators.fn_compute_synthetic_early_impulse_liq_align_2m(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  eps numeric := 1e-9;
  t_eval timestamptz := p_bucket_time + interval '2 minutes';
  v_open15 numeric;
  v_close2 numeric;
  v_close_eval numeric;
  v_atr1m numeric;
  v_r_early numeric;
  v_atr_pct numeric;
  v_r_vol numeric;
  v_mu_r numeric;
  v_sd_r numeric;
  v_z_r numeric;
  v_depth_skew numeric;
  v_slip_skew numeric;
  v_spread numeric;
  v_mu_spread numeric;
  v_sd_spread numeric;
  v_z_spread numeric;
  v_imb numeric;
  v_liq_align numeric;
  v_signal numeric;
  v_src_ob timestamptz;
  v_q jsonb;
begin
  select open::numeric into v_open15
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time = p_bucket_time;

  select close::numeric into v_close2
  from indicators.ohlcv_1m
  where pair = p_pair and bucket_time = t_eval;

  v_close_eval := v_close2;

  v_atr1m := indicators.fn_syn_iv_value(p_pair, t_eval, 'atr_14_1m', 'v1', true);

  if v_open15 is not null and v_close2 is not null and v_open15 <> 0 then
    v_r_early := ln(v_close2 / v_open15);
  end if;

  if v_atr1m is not null and v_close_eval is not null and v_close_eval <> 0 then
    v_atr_pct := v_atr1m / v_close_eval;
  end if;

  if v_r_early is not null and coalesce(v_atr_pct,0) <> 0 then
    v_r_vol := v_r_early / v_atr_pct;
  end if;

  with hist as (
    select (((c.close::numeric - c.open::numeric) / nullif(c.open::numeric, 0)) /
      nullif((iv.v1::numeric / nullif(c.close::numeric,0)), 0)) as r_vol
    from indicators.ohlcv_1m c
    left join indicators.indicator_values iv
      on iv.pair = c.pair and iv.bucket_time = c.bucket_time and iv.config_id = 'atr_14_1m'
    where c.pair = p_pair and c.bucket_time < t_eval
    order by c.bucket_time desc
    limit 720
  )
  select avg(r_vol), stddev_samp(r_vol) into v_mu_r, v_sd_r
  from hist
  where r_vol is not null;

  if v_r_vol is not null and coalesce(v_sd_r,0) <> 0 then
    v_z_r := (v_r_vol - v_mu_r) / v_sd_r;
  elsif v_r_vol is not null then
    v_z_r := v_r_vol;
  end if;

  with ob as (
    select *
    from indicators.order_book_indicators
    where pair = p_pair
      and captured_at <= t_eval
      and captured_at > t_eval - interval '5 minutes'
    order by captured_at desc
    limit 1
  )
  select
    captured_at,
    imbalance::numeric,
    spread_pct::numeric,
    ln((coalesce(bid_depth_25bps::numeric,0) + eps) / (coalesce(ask_depth_25bps::numeric,0) + eps)),
    ln((coalesce(slippage_sell_100::numeric,0) + eps) / (coalesce(slippage_buy_100::numeric,0) + eps))
  into v_src_ob, v_imb, v_spread, v_depth_skew, v_slip_skew
  from ob;

  with h as (
    select spread_pct::numeric as s
    from indicators.order_book_indicators
    where pair = p_pair and captured_at < t_eval
    order by captured_at desc
    limit 720
  )
  select avg(s), stddev_samp(s) into v_mu_spread, v_sd_spread from h;

  if v_spread is not null and coalesce(v_sd_spread,0) <> 0 then
    v_z_spread := (v_spread - v_mu_spread) / v_sd_spread;
  else
    v_z_spread := 0;
  end if;

  if v_z_r is not null and v_imb is not null then
    v_liq_align :=
      0.60 * tanh(v_imb) +
      0.30 * tanh(coalesce(v_depth_skew,0)) -
      0.20 * tanh(coalesce(v_slip_skew,0)) -
      0.30 * tanh(coalesce(v_z_spread,0));
    v_signal := v_z_r * v_liq_align;
  end if;

  v_q := jsonb_build_object(
    'missing_open_15m', v_open15 is null,
    'missing_close_tplus2', v_close2 is null,
    'missing_atr_14_1m', v_atr1m is null,
    'missing_order_book', v_src_ob is null,
    'stale_order_book', false
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_early_impulse_liq_align_tplus2',
    v_signal,
    v_z_r,
    v_liq_align,
    v_depth_skew,
    v_z_spread,
    greatest(t_eval, coalesce(v_src_ob, t_eval)),
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_early_impulse_liq_align_2m(text,timestamptz) is
  'Computes early impulse x liquidity alignment score at t+2m using order-book context.';

create or replace function indicators.fn_compute_synthetic_oi_funding_impulse_2m(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  eps numeric := 1e-9;
  t_eval timestamptz := p_bucket_time + interval '2 minutes';
  v_open15 numeric;
  v_close2 numeric;
  v_atr1m numeric;
  v_r_early numeric;
  v_atr_pct numeric;
  v_r_vol numeric;
  v_mu_r numeric;
  v_sd_r numeric;
  v_z_r numeric;
  v_oi_acc numeric;
  v_oi_roc numeric;
  v_fund numeric;
  v_basis numeric;
  v_mu_oi_acc numeric;
  v_sd_oi_acc numeric;
  v_mu_oi_roc numeric;
  v_sd_oi_roc numeric;
  v_mu_fund numeric;
  v_sd_fund numeric;
  v_mu_basis numeric;
  v_sd_basis numeric;
  v_z_oi_acc numeric;
  v_z_oi_roc numeric;
  v_z_fund numeric;
  v_z_basis numeric;
  v_oi_support numeric;
  v_crowding numeric;
  v_signal numeric;
  v_q jsonb;
begin
  select open::numeric into v_open15
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time = p_bucket_time;

  select close::numeric into v_close2
  from indicators.ohlcv_1m
  where pair = p_pair and bucket_time = t_eval;

  v_atr1m := indicators.fn_syn_iv_value(p_pair, t_eval, 'atr_14_1m', 'v1', true);

  if v_open15 is not null and v_close2 is not null and v_open15 <> 0 then
    v_r_early := ln(v_close2 / v_open15);
  end if;
  if v_atr1m is not null and v_close2 is not null and v_close2 <> 0 then
    v_atr_pct := v_atr1m / v_close2;
  end if;
  if v_r_early is not null and coalesce(v_atr_pct,0) <> 0 then
    v_r_vol := v_r_early / v_atr_pct;
  end if;

  with hist as (
    select (((c.close::numeric - c.open::numeric) / nullif(c.open::numeric, 0)) /
      nullif((iv.v1::numeric / nullif(c.close::numeric,0)), 0)) as r_vol
    from indicators.ohlcv_1m c
    left join indicators.indicator_values iv
      on iv.pair = c.pair and iv.bucket_time = c.bucket_time and iv.config_id = 'atr_14_1m'
    where c.pair = p_pair and c.bucket_time < t_eval
    order by c.bucket_time desc
    limit 720
  )
  select avg(r_vol), stddev_samp(r_vol) into v_mu_r, v_sd_r
  from hist
  where r_vol is not null;

  if v_r_vol is not null and coalesce(v_sd_r,0) <> 0 then
    v_z_r := (v_r_vol - v_mu_r) / v_sd_r;
  elsif v_r_vol is not null then
    v_z_r := v_r_vol;
  end if;

  select
    oi_acceleration::numeric,
    oi_roc_1h::numeric,
    funding_oi_pressure::numeric,
    basis_pct::numeric
  into v_oi_acc, v_oi_roc, v_fund, v_basis
  from indicators.oi_features
  where pair = p_pair and bucket_time = p_bucket_time;

  with hist as (
    select
      oi_acceleration::numeric as oi_acc,
      oi_roc_1h::numeric as oi_roc,
      funding_oi_pressure::numeric as fund,
      basis_pct::numeric as basis
    from indicators.oi_features
    where pair = p_pair and bucket_time < p_bucket_time
    order by bucket_time desc
    limit 96
  )
  select
    avg(oi_acc), stddev_samp(oi_acc),
    avg(oi_roc), stddev_samp(oi_roc),
    avg(fund), stddev_samp(fund),
    avg(basis), stddev_samp(basis)
  into
    v_mu_oi_acc, v_sd_oi_acc,
    v_mu_oi_roc, v_sd_oi_roc,
    v_mu_fund, v_sd_fund,
    v_mu_basis, v_sd_basis
  from hist;

  v_z_oi_acc := case when v_oi_acc is not null and coalesce(v_sd_oi_acc,0) <> 0 then (v_oi_acc - v_mu_oi_acc) / v_sd_oi_acc else 0 end;
  v_z_oi_roc := case when v_oi_roc is not null and coalesce(v_sd_oi_roc,0) <> 0 then (v_oi_roc - v_mu_oi_roc) / v_sd_oi_roc else 0 end;
  v_z_fund := case when v_fund is not null and coalesce(v_sd_fund,0) <> 0 then (v_fund - v_mu_fund) / v_sd_fund else 0 end;
  v_z_basis := case when v_basis is not null and coalesce(v_sd_basis,0) <> 0 then (v_basis - v_mu_basis) / v_sd_basis else 0 end;

  v_oi_support := 0.7 * v_z_oi_acc + 0.3 * v_z_oi_roc;
  v_crowding := 0.6 * v_z_fund + 0.4 * v_z_basis;

  if v_z_r is not null then
    v_signal := v_z_r * tanh(v_oi_support)
      - 0.50 * abs(v_z_r) * tanh(greatest(v_crowding, 0.0)) * sign(v_z_r);
  end if;

  v_q := jsonb_build_object(
    'missing_open_15m', v_open15 is null,
    'missing_close_tplus2', v_close2 is null,
    'missing_oi_features', v_oi_acc is null or v_oi_roc is null,
    'missing_funding_basis', v_fund is null or v_basis is null
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_oi_funding_impulse_tplus2',
    v_signal,
    v_z_r,
    v_oi_support,
    v_crowding,
    v_z_oi_acc,
    greatest(t_eval, p_bucket_time),
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_oi_funding_impulse_2m(text,timestamptz) is
  'Computes t+2m impulse confirmation using OI acceleration, OI ROC, funding pressure, and basis.';

create or replace function indicators.fn_compute_synthetic_early_momentum_divergence(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  t_eval timestamptz := p_bucket_time + interval '1 minute';
  v_peak3 numeric;
  v_close_eval numeric;
  v_price_roc numeric;
  v_rsi_now numeric;
  v_rsi_prev numeric;
  v_rsi_roc numeric;
  v_macd_now numeric;
  v_macd_prev numeric;
  v_macd_accel numeric;
  v_cvd_now numeric;
  v_cvd_prev numeric;
  v_cvd_roc numeric;
  v_indicator_mom numeric;
  v_div_raw numeric;
  v_emds numeric;
  v_q jsonb;
begin
  select max(close::numeric)
  into v_peak3
  from indicators.ohlcv_1m
  where pair = p_pair
    and bucket_time in (p_bucket_time - interval '3 minute', p_bucket_time - interval '2 minute', p_bucket_time - interval '1 minute');

  select close::numeric into v_close_eval
  from indicators.ohlcv_1m
  where pair = p_pair and bucket_time = t_eval;

  if v_peak3 is not null and v_peak3 <> 0 and v_close_eval is not null then
    v_price_roc := (v_close_eval - v_peak3) / v_peak3;
  end if;

  v_rsi_now := indicators.fn_syn_iv_value(p_pair, p_bucket_time, 'rsi_7_5m', 'v1', false);
  v_rsi_prev := indicators.fn_syn_iv_value(p_pair, p_bucket_time - interval '5 minutes', 'rsi_7_5m', 'v1', false);
  if v_rsi_now is not null and v_rsi_prev is not null then
    v_rsi_roc := (v_rsi_now - v_rsi_prev) / 100.0;
  end if;

  v_macd_now := indicators.fn_syn_iv_value(p_pair, p_bucket_time, 'macd_8_17_9_5m', 'v3', false);
  v_macd_prev := indicators.fn_syn_iv_value(p_pair, p_bucket_time - interval '5 minutes', 'macd_8_17_9_5m', 'v3', false);
  if v_macd_now is not null and v_macd_prev is not null then
    v_macd_accel := v_macd_now - v_macd_prev;
  end if;

  v_cvd_now := indicators.fn_syn_iv_value(p_pair, t_eval, 'cvd_20_1m', 'v1', true);
  v_cvd_prev := indicators.fn_syn_iv_value(p_pair, t_eval - interval '5 minutes', 'cvd_20_1m', 'v1', true);
  if v_cvd_now is not null and v_cvd_prev is not null then
    v_cvd_roc := (v_cvd_now - v_cvd_prev) / nullif(abs(v_cvd_prev) + 1e-9, 0);
  end if;

  if v_rsi_roc is not null and v_macd_accel is not null and v_cvd_roc is not null then
    v_indicator_mom := (v_rsi_roc + sign(v_macd_accel) * 0.5 + v_cvd_roc) / 2.5;
  end if;

  if v_indicator_mom is not null and v_price_roc is not null then
    v_div_raw := v_indicator_mom - sign(v_price_roc);
    v_emds := v_div_raw * abs(v_price_roc) * 100;
  end if;

  v_q := jsonb_build_object(
    'missing_price_boundary', v_price_roc is null,
    'missing_rsi_7_5m', v_rsi_now is null,
    'missing_macd_fast_hist', v_macd_now is null,
    'missing_cvd_20_1m', v_cvd_now is null
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_early_momentum_divergence_tplus1',
    v_emds,
    v_price_roc,
    v_rsi_roc,
    v_macd_accel,
    v_cvd_roc,
    t_eval,
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_early_momentum_divergence(text,timestamptz) is
  'Computes early momentum divergence score using 1m boundary price ROC and RSI/MACD/CVD internals.';

create or replace function indicators.fn_compute_synthetic_order_flow_accel_regime(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  eps numeric := 1e-9;
  t_eval timestamptz := p_bucket_time + interval '2 minutes';
  v_cvd_now numeric;
  v_cvd_prev numeric;
  v_cvd_prev2 numeric;
  v_cvd_vel_now numeric;
  v_cvd_vel_prev numeric;
  v_cvd_accel numeric;
  v_bid25 numeric;
  v_ask25 numeric;
  v_depth_ratio numeric;
  v_ob_pressure_now numeric;
  v_bid25_prev numeric;
  v_ask25_prev numeric;
  v_ob_pressure_prev numeric;
  v_ob_pressure_roc numeric;
  v_vol_t0 numeric;
  v_vol_avg3 numeric;
  v_vol_surge numeric;
  v_close_t0 numeric;
  v_close_t2 numeric;
  v_price_roc_2m numeric;
  v_flow_mom numeric;
  v_ofar numeric;
  v_q jsonb;
begin
  v_cvd_now := indicators.fn_syn_iv_value(p_pair, p_bucket_time, 'cvd_50_5m', 'v1', false);
  v_cvd_prev := indicators.fn_syn_iv_value(p_pair, p_bucket_time - interval '5 minutes', 'cvd_50_5m', 'v1', false);
  v_cvd_prev2 := indicators.fn_syn_iv_value(p_pair, p_bucket_time - interval '10 minutes', 'cvd_50_5m', 'v1', false);

  if v_cvd_now is not null and v_cvd_prev is not null then
    v_cvd_vel_now := v_cvd_now - v_cvd_prev;
  end if;
  if v_cvd_prev is not null and v_cvd_prev2 is not null then
    v_cvd_vel_prev := v_cvd_prev - v_cvd_prev2;
  end if;
  if v_cvd_vel_now is not null and v_cvd_vel_prev is not null then
    v_cvd_accel := v_cvd_vel_now - v_cvd_vel_prev;
  end if;

  with ob as (
    select *
    from indicators.order_book_indicators
    where pair = p_pair
      and captured_at <= t_eval
      and captured_at > t_eval - interval '5 minutes'
    order by captured_at desc
    limit 1
  )
  select bid_depth_25bps::numeric, ask_depth_25bps::numeric, depth_ratio::numeric
  into v_bid25, v_ask25, v_depth_ratio
  from ob;

  with ob as (
    select *
    from indicators.order_book_indicators
    where pair = p_pair
      and captured_at <= t_eval - interval '1 minutes'
      and captured_at > t_eval - interval '6 minutes'
    order by captured_at desc
    limit 1
  )
  select bid_depth_25bps::numeric, ask_depth_25bps::numeric
  into v_bid25_prev, v_ask25_prev
  from ob;

  if v_bid25 is not null and v_ask25 is not null then
    v_ob_pressure_now := (v_bid25 - v_ask25) / (v_bid25 + v_ask25 + eps);
  end if;
  if v_bid25_prev is not null and v_ask25_prev is not null then
    v_ob_pressure_prev := (v_bid25_prev - v_ask25_prev) / (v_bid25_prev + v_ask25_prev + eps);
  end if;
  if v_ob_pressure_now is not null and v_ob_pressure_prev is not null then
    v_ob_pressure_roc := v_ob_pressure_now - v_ob_pressure_prev;
  end if;

  select volume::numeric into v_vol_t0
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time = p_bucket_time;

  select avg(volume::numeric) into v_vol_avg3
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time in (
    p_bucket_time - interval '15 minutes',
    p_bucket_time - interval '30 minutes',
    p_bucket_time - interval '45 minutes'
  );

  if v_vol_t0 is not null and coalesce(v_vol_avg3,0) <> 0 then
    v_vol_surge := (v_vol_t0 - v_vol_avg3) / v_vol_avg3;
  end if;

  select close::numeric into v_close_t0
  from indicators.ohlcv_1m
  where pair = p_pair and bucket_time = p_bucket_time;

  select close::numeric into v_close_t2
  from indicators.ohlcv_1m
  where pair = p_pair and bucket_time = t_eval;

  if v_close_t0 is not null and v_close_t2 is not null and v_close_t0 <> 0 then
    v_price_roc_2m := (v_close_t2 - v_close_t0) / v_close_t0;
  end if;

  if v_cvd_accel is not null and v_ob_pressure_roc is not null and v_vol_surge is not null then
    v_flow_mom := v_cvd_accel * 0.4 + v_ob_pressure_roc * 0.3 + v_vol_surge * 0.3;
  end if;

  if v_flow_mom is not null and v_price_roc_2m is not null then
    v_ofar := v_flow_mom * sign(v_price_roc_2m) * 10;
  end if;

  v_q := jsonb_build_object(
    'missing_cvd_50_5m', v_cvd_now is null,
    'missing_order_book', v_bid25 is null or v_ask25 is null,
    'missing_volume_context', v_vol_t0 is null or v_vol_avg3 is null,
    'missing_price_boundary', v_price_roc_2m is null
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_order_flow_accel_regime_tplus2',
    v_ofar,
    v_cvd_accel,
    v_ob_pressure_roc,
    v_vol_surge,
    v_depth_ratio,
    t_eval,
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_order_flow_accel_regime(text,timestamptz) is
  'Computes order-flow acceleration regime score from CVD acceleration, OB pressure ROC, and volume surge.';

create or replace function indicators.fn_compute_synthetic_for_bucket(
  p_pair text,
  p_bucket_time timestamptz,
  p_config_id text
)
returns void
language plpgsql
as $$
begin
  case p_config_id
    when 'syn_mtf_signed_efficiency_ratio_5m12_15m8' then
      perform indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio(p_pair, p_bucket_time);
    when 'syn_rsi_velocity_5m_3bar_z20' then
      perform indicators.fn_compute_synthetic_rsi_velocity_5m(p_pair, p_bucket_time);
    when 'syn_early_impulse_liq_align_tplus2' then
      perform indicators.fn_compute_synthetic_early_impulse_liq_align_2m(p_pair, p_bucket_time);
    when 'syn_oi_funding_impulse_tplus2' then
      perform indicators.fn_compute_synthetic_oi_funding_impulse_2m(p_pair, p_bucket_time);
    when 'syn_early_momentum_divergence_tplus1' then
      perform indicators.fn_compute_synthetic_early_momentum_divergence(p_pair, p_bucket_time);
    when 'syn_order_flow_accel_regime_tplus2' then
      perform indicators.fn_compute_synthetic_order_flow_accel_regime(p_pair, p_bucket_time);
    else
      raise exception 'Unknown synthetic config_id: %', p_config_id;
  end case;
end;
$$;

comment on function indicators.fn_compute_synthetic_for_bucket(text,timestamptz,text) is
  'Dispatcher: compute one synthetic indicator for pair/bucket/config_id.';

create or replace function indicators.fn_compute_all_synthetic_for_bucket(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  r record;
begin
  for r in
    select config_id
    from indicators.synthetic_indicator_configs
    where is_active
    order by config_id
  loop
    perform indicators.fn_compute_synthetic_for_bucket(p_pair, p_bucket_time, r.config_id);
  end loop;
end;
$$;

comment on function indicators.fn_compute_all_synthetic_for_bucket(text,timestamptz) is
  'Computes all active synthetic indicators for a pair and 15m bucket boundary.';
