create or replace view indicators.v_synthetic_signal_inputs as
with x as (
  select
    s.pair,
    s.bucket_time,
    s.config_id,
    s.v1,
    s.v2,
    s.v3,
    s.v4,
    s.v5,
    s.computed_at,
    s.quality_flags,
    c.decision_phase
  from indicators.synthetic_indicator_values s
  join indicators.synthetic_indicator_configs c using (config_id)
)
select
  pair,
  bucket_time,
  max(v1) filter (where config_id = 'syn_mtf_signed_efficiency_ratio_5m12_15m8') as syn_mtf_signed_efficiency_ratio,
  max(v1) filter (where config_id = 'syn_rsi_velocity_5m_3bar_z20') as syn_rsi_velocity_5m,
  max(v1) filter (where config_id = 'syn_early_impulse_liq_align_tplus2') as syn_early_impulse_liq_align_2m,
  max(v1) filter (where config_id = 'syn_oi_funding_impulse_tplus2') as syn_oi_funding_impulse_2m,
  max(v1) filter (where config_id = 'syn_early_momentum_divergence_tplus1') as syn_early_momentum_divergence,
  max(v1) filter (where config_id = 'syn_order_flow_accel_regime_tplus2') as syn_order_flow_accel_regime,

  max(v2) filter (where config_id = 'syn_mtf_signed_efficiency_ratio_5m12_15m8') as syn_mtf_er_5m,
  max(v3) filter (where config_id = 'syn_mtf_signed_efficiency_ratio_5m12_15m8') as syn_mtf_er_15m,

  max(v2) filter (where config_id = 'syn_early_impulse_liq_align_tplus2') as syn_early_impulse_z_r,
  max(v3) filter (where config_id = 'syn_early_impulse_liq_align_tplus2') as syn_early_impulse_liq_align,

  max(v2) filter (where config_id = 'syn_oi_funding_impulse_tplus2') as syn_oi_funding_z_r,
  max(v3) filter (where config_id = 'syn_oi_funding_impulse_tplus2') as syn_oi_support,
  max(v4) filter (where config_id = 'syn_oi_funding_impulse_tplus2') as syn_oi_crowding,

  max(v2) filter (where config_id = 'syn_early_momentum_divergence_tplus1') as syn_emds_price_roc,
  max(v3) filter (where config_id = 'syn_early_momentum_divergence_tplus1') as syn_emds_rsi_roc,

  max(v2) filter (where config_id = 'syn_order_flow_accel_regime_tplus2') as syn_ofar_cvd_accel,
  max(v3) filter (where config_id = 'syn_order_flow_accel_regime_tplus2') as syn_ofar_ob_pressure_roc,
  max(v4) filter (where config_id = 'syn_order_flow_accel_regime_tplus2') as syn_ofar_vol_surge,

  max(computed_at) as synthetic_computed_at,
  max(case when decision_phase = 't_plus_1m' then 1 else 0 end) as has_t_plus_1m_features,
  max(case when decision_phase = 't_plus_2m' then 1 else 0 end) as has_t_plus_2m_features
from x
group by pair, bucket_time;

comment on view indicators.v_synthetic_signal_inputs is
  'Serving view for signal scripts: pivots six synthetic indicators to one row per pair/bucket_time.';
