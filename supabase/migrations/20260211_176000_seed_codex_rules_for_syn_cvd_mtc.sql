-- Seed codex rules for deployable syn_new winners:
-- - syn_cvd_price_divergence_velocity_15m5_tplus2
-- - syn_multitimeframe_trend_confluence_tplus2
-- Thresholds/accuracy/support are from:
-- scripts/output/syn_new_eval/20260211T163043Z/results.json

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
  -- CVD price divergence velocity
  ('btc_syn_cvd_div_15m5_up_le_n2p6735821664', 'BTC-USD', 'syn_cvd_price_divergence_velocity_15m5_tplus2', '<=', -2.67358216640126, 'up',   0.6867469879518072,  83, 0.050455927051671734, true),
  ('btc_syn_cvd_div_15m5_down_ge_2p9800626295', 'BTC-USD', 'syn_cvd_price_divergence_velocity_15m5_tplus2', '>=',  2.98006262953417, 'down', 0.6785714285714286,  84, 0.051063829787234040, true),
  ('eth_syn_cvd_div_15m5_up_le_n2p1621666681', 'ETH-USD', 'syn_cvd_price_divergence_velocity_15m5_tplus2', '<=', -2.16216666809172, 'up',   0.6585365853658537, 123, 0.074954296160877510, true),
  ('eth_syn_cvd_div_15m5_down_ge_1p7811307823', 'ETH-USD', 'syn_cvd_price_divergence_velocity_15m5_tplus2', '>=',  1.78113078225852, 'down', 0.6533333333333333, 225, 0.137111517367458860, true),
  ('sol_syn_cvd_div_15m5_up_le_n1p8259998716', 'SOL-USD', 'syn_cvd_price_divergence_velocity_15m5_tplus2', '<=', -1.82599987161073, 'up',   0.6149425287356322, 174, 0.107076923076923080, true),
  ('sol_syn_cvd_div_15m5_down_ge_2p3566008332', 'SOL-USD', 'syn_cvd_price_divergence_velocity_15m5_tplus2', '>=',  2.35660083320023, 'down', 0.6397058823529411, 136, 0.083692307692307690, true),

  -- Multi-timeframe trend confluence
  ('btc_syn_mtc_up_ge_3p0',   'BTC-USD', 'syn_multitimeframe_trend_confluence_tplus2', '>=', 3.0, 'up',   0.6793650793650794, 630, 0.4259634888438134, true),
  ('btc_syn_mtc_down_le_1p0', 'BTC-USD', 'syn_multitimeframe_trend_confluence_tplus2', '<=', 1.0, 'down', 0.6702002355712603, 849, 0.5740365111561866, true),
  ('eth_syn_mtc_up_ge_3p0',   'ETH-USD', 'syn_multitimeframe_trend_confluence_tplus2', '>=', 3.0, 'up',   0.6710334788937409, 687, 0.4654471544715447, true),
  ('eth_syn_mtc_down_le_1p0', 'ETH-USD', 'syn_multitimeframe_trend_confluence_tplus2', '<=', 1.0, 'down', 0.6970849176172370, 789, 0.5345528455284553, true),
  ('sol_syn_mtc_up_ge_3p0',   'SOL-USD', 'syn_multitimeframe_trend_confluence_tplus2', '>=', 3.0, 'up',   0.6831091180866966, 669, 0.4575923392612859, true),
  ('sol_syn_mtc_down_le_1p0', 'SOL-USD', 'syn_multitimeframe_trend_confluence_tplus2', '<=', 1.0, 'down', 0.7099621689785625, 793, 0.5424076607387140, true)
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
