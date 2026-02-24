-- Add deployable synthetic configs from evaluated syn_new candidates:
-- 1) cvd_price_divergence_velocity
-- 2) multitimeframe_trend_confluence

insert into indicators.synthetic_indicator_configs (
  config_id,
  indicator_name,
  category,
  timeframe,
  decision_phase,
  params,
  output_columns,
  description,
  is_active
)
values
  (
    'syn_cvd_price_divergence_velocity_15m5_tplus2',
    'cvd_price_divergence_velocity',
    'synthetic_orderflow_divergence',
    '15m',
    't_plus_2m',
    jsonb_build_object(
      'cvd_config', 'cvd_50_15m',
      'atr_config', 'atr_14_15m',
      'lag_bars_15m', 5,
      'std_window', 20,
      'eps', 1e-9
    ),
    jsonb_build_object(
      'v1', 'value',
      'v2', 'cvd_norm',
      'v3', 'price_norm',
      'v4', 'cvd_std_20',
      'v5', 'atr_14_15m'
    ),
    'Divergence between normalized 15m CVD velocity and ATR-scaled 15m price velocity.',
    true
  ),
  (
    'syn_multitimeframe_trend_confluence_tplus2',
    'multitimeframe_trend_confluence',
    'synthetic_trend_confluence',
    '15m',
    't_plus_2m',
    jsonb_build_object(
      'supertrend_5m_config', 'supertrend_10_3_5m',
      'supertrend_15m_config', 'supertrend_10_3_15m',
      'ema_fast_config', 'ema_9_15m',
      'ema_slow_config', 'ema_21_15m',
      'vol_filter_threshold', 0.0012
    ),
    jsonb_build_object(
      'v1', 'confluence_score',
      'v2', 'raw_score',
      'v3', 'vol_filter',
      'v4', 'ema_slope_delta',
      'v5', 'atr_5m_simple_pct'
    ),
    'Directional confluence score from 5m/15m supertrend plus EMA slope regime with a 5m volatility filter.',
    true
  )
on conflict (config_id) do update
set
  indicator_name = excluded.indicator_name,
  category = excluded.category,
  timeframe = excluded.timeframe,
  decision_phase = excluded.decision_phase,
  params = excluded.params,
  output_columns = excluded.output_columns,
  description = excluded.description,
  is_active = excluded.is_active;

create or replace function indicators.fn_compute_synthetic_cvd_price_divergence_velocity(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  eps numeric := 1e-9;
  v_cvd_t0 numeric;
  v_cvd_t5 numeric;
  v_close_t0 numeric;
  v_close_t5 numeric;
  v_atr_15m numeric;
  v_cvd_sd20 numeric;
  v_cvd_norm numeric;
  v_price_norm numeric;
  v_value numeric;
  v_q jsonb;
begin
  select v1::numeric into v_cvd_t0
  from indicators.indicator_values
  where pair = p_pair
    and config_id = 'cvd_50_15m'
    and bucket_time = p_bucket_time;

  select v1::numeric into v_cvd_t5
  from indicators.indicator_values
  where pair = p_pair
    and config_id = 'cvd_50_15m'
    and bucket_time = p_bucket_time - interval '75 minutes';

  select close::numeric into v_close_t0
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time = p_bucket_time;

  select close::numeric into v_close_t5
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time = p_bucket_time - interval '75 minutes';

  select v1::numeric into v_atr_15m
  from indicators.indicator_values
  where pair = p_pair
    and config_id = 'atr_14_15m'
    and bucket_time = p_bucket_time;

  with s as (
    select v1::numeric as x
    from indicators.indicator_values
    where pair = p_pair
      and config_id = 'cvd_50_15m'
      and bucket_time <= p_bucket_time
    order by bucket_time desc
    limit 20
  )
  select stddev_samp(x) into v_cvd_sd20 from s;

  if v_cvd_t0 is not null and v_cvd_t5 is not null and v_close_t0 is not null and v_close_t5 is not null and v_atr_15m is not null then
    v_cvd_norm := (v_cvd_t0 - v_cvd_t5) / (coalesce(v_cvd_sd20, 0) + eps);
    v_price_norm := (v_close_t0 - v_close_t5) / ((v_atr_15m * sqrt(5.0)) + eps);
    v_value := v_cvd_norm - v_price_norm;
  end if;

  v_q := jsonb_build_object(
    'missing_cvd_t0', v_cvd_t0 is null,
    'missing_cvd_t5', v_cvd_t5 is null,
    'missing_close_t0', v_close_t0 is null,
    'missing_close_t5', v_close_t5 is null,
    'missing_atr_14_15m', v_atr_15m is null,
    'low_cvd_history', v_cvd_sd20 is null
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_cvd_price_divergence_velocity_15m5_tplus2',
    v_value,
    v_cvd_norm,
    v_price_norm,
    v_cvd_sd20,
    v_atr_15m,
    p_bucket_time,
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_cvd_price_divergence_velocity(text,timestamptz) is
  'Computes CVD-vs-price normalized velocity divergence on 15m horizon (lag=5 bars).';

create or replace function indicators.fn_compute_synthetic_multitimeframe_trend_confluence(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  v_st_5m numeric;
  v_st_15m numeric;
  v_ema9_t0 numeric;
  v_ema9_t1 numeric;
  v_ema21_t0 numeric;
  v_ema21_t1 numeric;
  v_close_5m_t0 numeric;
  v_high_5m_t0 numeric;
  v_low_5m_t0 numeric;
  v_close_15m_t0 numeric;
  v_st_5m_dir numeric;
  v_st_15m_dir numeric;
  v_ema_slope numeric;
  v_ema_dir numeric;
  v_raw_score numeric;
  v_atr_5m_simple numeric;
  v_atr_5m_simple_pct numeric;
  v_vol_filter numeric;
  v_value numeric;
  v_q jsonb;
begin
  select v1::numeric into v_st_5m
  from indicators.indicator_values
  where pair = p_pair and config_id = 'supertrend_10_3_5m' and bucket_time = p_bucket_time;

  select v1::numeric into v_st_15m
  from indicators.indicator_values
  where pair = p_pair and config_id = 'supertrend_10_3_15m' and bucket_time = p_bucket_time;

  select v1::numeric into v_ema9_t0
  from indicators.indicator_values
  where pair = p_pair and config_id = 'ema_9_15m' and bucket_time = p_bucket_time;

  select v1::numeric into v_ema9_t1
  from indicators.indicator_values
  where pair = p_pair and config_id = 'ema_9_15m' and bucket_time = p_bucket_time - interval '15 minutes';

  select v1::numeric into v_ema21_t0
  from indicators.indicator_values
  where pair = p_pair and config_id = 'ema_21_15m' and bucket_time = p_bucket_time;

  select v1::numeric into v_ema21_t1
  from indicators.indicator_values
  where pair = p_pair and config_id = 'ema_21_15m' and bucket_time = p_bucket_time - interval '15 minutes';

  select close::numeric, high::numeric, low::numeric
  into v_close_5m_t0, v_high_5m_t0, v_low_5m_t0
  from indicators.ohlcv_5m
  where pair = p_pair and bucket_time = p_bucket_time;

  select close::numeric into v_close_15m_t0
  from indicators.ohlcv_15m
  where pair = p_pair and bucket_time = p_bucket_time;

  if v_st_5m is not null and v_close_5m_t0 is not null then
    v_st_5m_dir := case when v_st_5m < v_close_5m_t0 then 1.0 else -1.0 end;
  end if;
  if v_st_15m is not null and v_close_15m_t0 is not null then
    v_st_15m_dir := case when v_st_15m < v_close_15m_t0 then 1.0 else -1.0 end;
  end if;
  if v_ema9_t0 is not null and v_ema9_t1 is not null and v_ema21_t0 is not null and v_ema21_t1 is not null then
    v_ema_slope := (v_ema9_t0 - v_ema9_t1) - (v_ema21_t0 - v_ema21_t1);
    v_ema_dir := case when v_ema_slope > 0 then 1.0 else -1.0 end;
  end if;

  if v_st_5m_dir is not null and v_st_15m_dir is not null and v_ema_dir is not null then
    v_raw_score := v_st_5m_dir + v_st_15m_dir + v_ema_dir;
  end if;

  if v_high_5m_t0 is not null and v_low_5m_t0 is not null and v_close_5m_t0 is not null and v_close_5m_t0 <> 0 then
    v_atr_5m_simple := v_high_5m_t0 - v_low_5m_t0;
    v_atr_5m_simple_pct := v_atr_5m_simple / v_close_5m_t0;
    v_vol_filter := case when v_atr_5m_simple > 0.0012 * v_close_5m_t0 then 1.0 else 0.2 end;
  end if;

  if v_raw_score is not null and v_vol_filter is not null then
    v_value := v_raw_score * v_vol_filter;
  end if;

  v_q := jsonb_build_object(
    'missing_supertrend_5m', v_st_5m is null,
    'missing_supertrend_15m', v_st_15m is null,
    'missing_ema_context', v_ema_slope is null,
    'missing_ohlcv_5m', v_close_5m_t0 is null or v_high_5m_t0 is null or v_low_5m_t0 is null,
    'missing_ohlcv_15m_close', v_close_15m_t0 is null
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_multitimeframe_trend_confluence_tplus2',
    v_value,
    v_raw_score,
    v_vol_filter,
    v_ema_slope,
    v_atr_5m_simple_pct,
    p_bucket_time,
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_multitimeframe_trend_confluence(text,timestamptz) is
  'Computes trend confluence score from 5m/15m supertrend + EMA slope with volatility gating.';

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
    when 'syn_window_edge_57to01_eth_nonrolling_tplus2' then
      perform indicators.fn_compute_synthetic_window_edge_eth_nonrolling(p_pair, p_bucket_time);
    when 'syn_cvd_price_divergence_velocity_15m5_tplus2' then
      perform indicators.fn_compute_synthetic_cvd_price_divergence_velocity(p_pair, p_bucket_time);
    when 'syn_multitimeframe_trend_confluence_tplus2' then
      perform indicators.fn_compute_synthetic_multitimeframe_trend_confluence(p_pair, p_bucket_time);
    else
      raise exception 'Unknown synthetic config_id: %', p_config_id;
  end case;
end;
$$;

comment on function indicators.fn_compute_synthetic_for_bucket(text,timestamptz,text) is
  'Dispatcher: compute one synthetic indicator for pair/bucket/config_id (includes CVD divergence and MTF confluence candidates).';
