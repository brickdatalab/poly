-- Add codex signal rules for ETH non-rolling window-edge synthetic.

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
  (
    'eth_syn_window_edge_57to01_nonrolling_up_ge_0p0719108856',
    'ETH-USD',
    'syn_window_edge_57to01_eth_nonrolling_tplus2',
    '>=',
    0.0719108856117475,
    'up',
    0.676471,
    34,
    0.3820,
    true
  ),
  (
    'eth_syn_window_edge_57to01_nonrolling_down_le_n0p0639929142',
    'ETH-USD',
    'syn_window_edge_57to01_eth_nonrolling_tplus2',
    '<=',
    -0.0639929141611394,
    'down',
    0.592593,
    27,
    0.3034,
    true
  )
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
