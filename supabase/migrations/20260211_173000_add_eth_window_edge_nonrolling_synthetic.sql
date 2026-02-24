-- ETH-only non-rolling window-edge synthetic indicator.
-- Feature: pct_diff_57_to_01 = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100
-- Decision logic (from requested ETH non-rolling distribution):
--   - UP trigger:   pct_diff >  +0.0719108856117475   (67.6471% recent slice accuracy)
--   - DOWN trigger: pct_diff <  -0.0639929141611394   (59.2593% recent slice accuracy)

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
values (
  'syn_window_edge_57to01_eth_nonrolling_tplus2',
  'window_edge_57to01_nonrolling_eth',
  'synthetic_window_edge',
  '15m',
  't_plus_2m',
  jsonb_build_object(
    'pair_scope', 'ETH-USD',
    'up_threshold_pct', 0.0719108856117475,
    'down_threshold_pct', -0.0639929141611394,
    'base_accuracy_up', 0.676471,
    'base_accuracy_down', 0.592593,
    'decision_minute_offset', 2
  ),
  jsonb_build_object(
    'v1', 'pct_diff_57_to_01',
    'v2', 'direction_code',
    'v3', 'selected_base_accuracy',
    'v4', 'up_threshold_pct',
    'v5', 'down_threshold_pct'
  ),
  'ETH-only non-rolling window-edge feature. Computes :57 open -> :01 close percent difference and directional state for 15m market at t+2m.',
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

create or replace function indicators.fn_compute_synthetic_window_edge_eth_nonrolling(
  p_pair text,
  p_bucket_time timestamptz
)
returns void
language plpgsql
as $$
declare
  v_up_t constant numeric := 0.0719108856117475;
  v_down_t constant numeric := -0.0639929141611394;
  v_up_acc constant numeric := 0.676471;
  v_down_acc constant numeric := 0.592593;
  v_open57 numeric;
  v_close01 numeric;
  v_pct_diff numeric;
  v_dir numeric;
  v_sel_acc numeric;
  v_q jsonb;
begin
  -- ETH-only scope by design.
  if p_pair <> 'ETH-USD' then
    return;
  end if;

  select open::numeric into v_open57
  from indicators.ohlcv_1m
  where pair = p_pair
    and bucket_time = p_bucket_time - interval '3 minutes';

  select close::numeric into v_close01
  from indicators.ohlcv_1m
  where pair = p_pair
    and bucket_time = p_bucket_time + interval '1 minute';

  if v_open57 is not null and v_close01 is not null and v_open57 <> 0 then
    v_pct_diff := ((v_close01 - v_open57) / v_open57) * 100.0;
  end if;

  if v_pct_diff is null then
    v_dir := null;
    v_sel_acc := null;
  elsif v_pct_diff > v_up_t then
    v_dir := 1;
    v_sel_acc := v_up_acc;
  elsif v_pct_diff < v_down_t then
    v_dir := -1;
    v_sel_acc := v_down_acc;
  else
    v_dir := 0;
    v_sel_acc := null;
  end if;

  v_q := jsonb_build_object(
    'pair_scope_eth_only', true,
    'missing_open_57', v_open57 is null,
    'missing_close_01', v_close01 is null,
    'no_trigger_zone', v_dir = 0
  );

  perform indicators.fn_syn_upsert_value(
    p_pair,
    p_bucket_time,
    'syn_window_edge_57to01_eth_nonrolling_tplus2',
    v_pct_diff,
    v_dir,
    v_sel_acc,
    v_up_t,
    v_down_t,
    p_bucket_time + interval '1 minute',
    v_q
  );
end;
$$;

comment on function indicators.fn_compute_synthetic_window_edge_eth_nonrolling(text,timestamptz) is
  'ETH-only non-rolling window-edge synthetic: :57 open -> :01 close pct diff + directional state.';

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
    else
      raise exception 'Unknown synthetic config_id: %', p_config_id;
  end case;
end;
$$;

comment on function indicators.fn_compute_synthetic_for_bucket(text,timestamptz,text) is
  'Dispatcher: compute one synthetic indicator for pair/bucket/config_id (includes ETH window-edge synthetic).';
