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
  'syn_mtf_signed_efficiency_ratio_5m12_15m8',
  'mtf_signed_efficiency_ratio',
  'synthetic_mtf',
  '15m',
  't_plus_1m',
  '{"er_5m_lookback":12,"er_15m_lookback":8,"conflict_zone":-0.05,"aligned_strong":0.20}'::jsonb,
  '{"v1":"signal","v2":"er_5m","v3":"er_15m","v4":"abs_er_5m","v5":"abs_er_15m"}'::jsonb,
  'Product of 5m and 15m signed efficiency ratios. Positive when trends align, negative on conflict.',
  true
),
(
  'syn_rsi_velocity_5m_3bar_z20',
  'rsi_velocity_5m',
  'synthetic_momentum',
  '15m',
  't_plus_1m',
  '{"velocity_window_5m":3,"z_window_5m":20,"std_floor":0.5,"hourly_rsi_regime":[35,65]}'::jsonb,
  '{"v1":"z_velocity","v2":"raw_velocity","v3":"rsi_7_5m","v4":"rsi_14_1h","v5":"std_used"}'::jsonb,
  'Z-scored 5m RSI velocity aligned to 15m prediction horizon with hourly RSI context.',
  true
),
(
  'syn_early_impulse_liq_align_tplus2',
  'early_impulse_liquidity_alignment_2m',
  'synthetic_microstructure',
  '15m',
  't_plus_2m',
  '{"eval_offset_min":2,"z_window_1m":720,"max_orderbook_staleness_seconds":300}'::jsonb,
  '{"v1":"signal","v2":"z_r","v3":"liq_align","v4":"depth_skew","v5":"spread_z"}'::jsonb,
  'Combines early impulse return with order book alignment and spread conditions at t+2m.',
  true
),
(
  'syn_oi_funding_impulse_tplus2',
  'oi_funding_impulse_confirmation_2m',
  'synthetic_oi',
  '15m',
  't_plus_2m',
  '{"eval_offset_min":2,"oi_z_window_15m":96,"crowding_penalty":0.5}'::jsonb,
  '{"v1":"signal","v2":"z_r","v3":"oi_support","v4":"crowding","v5":"oi_acc_z"}'::jsonb,
  'Combines early impulse with OI/funding participation and crowding penalty at event boundary.',
  true
),
(
  'syn_early_momentum_divergence_tplus1',
  'early_momentum_divergence_score',
  'synthetic_divergence',
  '15m',
  't_plus_1m',
  '{"eval_offset_min":1,"price_peak_lookback_1m":3,"cvd_lookback_1m":5,"threshold_sigma":1.5}'::jsonb,
  '{"v1":"emds","v2":"price_roc_boundary","v3":"rsi_roc","v4":"macd_accel","v5":"cvd_roc"}'::jsonb,
  'Measures divergence between boundary price move and internal momentum (RSI/MACD/CVD).',
  true
),
(
  'syn_order_flow_accel_regime_tplus2',
  'order_flow_acceleration_regime',
  'synthetic_orderflow',
  '15m',
  't_plus_2m',
  '{"eval_offset_min":2,"cvd_velocity_lookback":2,"volume_lookback_15m":3,"threshold_sigma":0.8}'::jsonb,
  '{"v1":"ofar","v2":"cvd_accel","v3":"ob_pressure_roc","v4":"vol_surge","v5":"depth_ratio"}'::jsonb,
  'Order-flow acceleration regime score using CVD acceleration, OB pressure shift, and volume surge.',
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
