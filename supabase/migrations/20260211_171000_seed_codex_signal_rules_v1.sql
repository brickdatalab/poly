-- Seed codex realtime rules (v1).
-- Source: synthetic correlation scan with min support 5% from 2026-01-22 to 2026-02-11.

insert into indicators.codex_signal_rules (
  rule_id,
  pair,
  config_id,
  operator,
  threshold,
  prediction,
  base_accuracy,
  support_n,
  support_pct,
  is_active
)
values
  -- BTC-USD
  ('btc_syn_early_impulse_liq_align_tplus2_down_ge_1p205976', 'BTC-USD', 'syn_early_impulse_liq_align_tplus2', '>=', 1.205976, 'down', 0.6933, 75, 0.0513, true),
  ('btc_syn_early_momentum_divergence_tplus1_up_le_n0p189361', 'BTC-USD', 'syn_early_momentum_divergence_tplus1', '<=', -0.189361, 'up', 0.6400, 75, 0.0508, true),
  ('btc_syn_early_momentum_divergence_tplus1_down_ge_0p094863', 'BTC-USD', 'syn_early_momentum_divergence_tplus1', '>=', 0.094863, 'down', 0.6441, 444, 0.3006, true),
  ('btc_syn_oi_funding_impulse_tplus2_down_ge_1p331442', 'BTC-USD', 'syn_oi_funding_impulse_tplus2', '>=', 1.331442, 'down', 0.6538, 78, 0.0520, true),
  ('btc_syn_rsi_velocity_5m_3bar_z20_up_ge_1p489539', 'BTC-USD', 'syn_rsi_velocity_5m_3bar_z20', '>=', 1.489539, 'up', 0.6562, 96, 0.0576, true),
  ('btc_syn_rsi_velocity_5m_3bar_z20_down_le_n1p432481', 'BTC-USD', 'syn_rsi_velocity_5m_3bar_z20', '<=', -1.432481, 'down', 0.6552, 116, 0.0696, true),

  -- ETH-USD
  ('eth_syn_early_impulse_liq_align_tplus2_down_ge_1p289645', 'ETH-USD', 'syn_early_impulse_liq_align_tplus2', '>=', 1.289645, 'down', 0.6234, 77, 0.0527, true),
  ('eth_syn_early_momentum_divergence_tplus1_up_le_n0p177442', 'ETH-USD', 'syn_early_momentum_divergence_tplus1', '<=', -0.177442, 'up', 0.6573, 143, 0.0969, true),
  ('eth_syn_early_momentum_divergence_tplus1_down_ge_0p366086', 'ETH-USD', 'syn_early_momentum_divergence_tplus1', '>=', 0.366086, 'down', 0.6608, 171, 0.1159, true),
  ('eth_syn_mtf_signed_efficiency_ratio_down_ge_0p335248', 'ETH-USD', 'syn_mtf_signed_efficiency_ratio_5m12_15m8', '>=', 0.335248, 'down', 0.6250, 184, 0.0957, true),
  ('eth_syn_oi_funding_impulse_tplus2_up_le_n1p100426', 'ETH-USD', 'syn_oi_funding_impulse_tplus2', '<=', -1.100426, 'up', 0.6310, 84, 0.0561, true),
  ('eth_syn_rsi_velocity_5m_3bar_z20_up_ge_1p514696', 'ETH-USD', 'syn_rsi_velocity_5m_3bar_z20', '>=', 1.514696, 'up', 0.6373, 102, 0.0613, true),
  ('eth_syn_rsi_velocity_5m_3bar_z20_down_le_n1p625252', 'ETH-USD', 'syn_rsi_velocity_5m_3bar_z20', '<=', -1.625252, 'down', 0.6941, 85, 0.0511, true),

  -- SOL-USD
  ('sol_syn_early_impulse_liq_align_tplus2_down_le_n0p567129', 'SOL-USD', 'syn_early_impulse_liq_align_tplus2', '<=', -0.567129, 'down', 0.6132, 106, 0.0737, true),
  ('sol_syn_early_momentum_divergence_tplus1_up_le_n0p384006', 'SOL-USD', 'syn_early_momentum_divergence_tplus1', '<=', -0.384006, 'up', 0.6667, 75, 0.0513, true),
  ('sol_syn_early_momentum_divergence_tplus1_down_ge_0p645655', 'SOL-USD', 'syn_early_momentum_divergence_tplus1', '>=', 0.645655, 'down', 0.6316, 76, 0.0520, true),
  ('sol_syn_mtf_signed_efficiency_ratio_down_ge_0p435057', 'SOL-USD', 'syn_mtf_signed_efficiency_ratio_5m12_15m8', '>=', 0.435057, 'down', 0.6765, 102, 0.0536, true),
  ('sol_syn_oi_funding_impulse_tplus2_down_ge_1p606966', 'SOL-USD', 'syn_oi_funding_impulse_tplus2', '>=', 1.606966, 'down', 0.7273, 77, 0.0519, true),
  ('sol_syn_rsi_velocity_5m_3bar_z20_up_ge_1p604583', 'SOL-USD', 'syn_rsi_velocity_5m_3bar_z20', '>=', 1.604583, 'up', 0.6588, 85, 0.0516, true),
  ('sol_syn_rsi_velocity_5m_3bar_z20_down_le_n1p525095', 'SOL-USD', 'syn_rsi_velocity_5m_3bar_z20', '<=', -1.525095, 'down', 0.6421, 95, 0.0577, true)
on conflict (rule_id) do update
set
  pair = excluded.pair,
  config_id = excluded.config_id,
  operator = excluded.operator,
  threshold = excluded.threshold,
  prediction = excluded.prediction,
  base_accuracy = excluded.base_accuracy,
  support_n = excluded.support_n,
  support_pct = excluded.support_pct,
  is_active = excluded.is_active;
