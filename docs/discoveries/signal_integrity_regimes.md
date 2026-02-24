# Signal Integrity Regimes

This report summarizes regime-aware integrity gating for BTC/ETH codex rules.

## Top Rules by Recommendation

| rule_id | pair | config_id | recommended_active | rule_accuracy | regime_gate | walkforward_gate |
|---|---|---|---:|---:|---:|---:|
| eth_syn_mtc_up_ge_3p0 | ETH-USD | syn_multitimeframe_trend_confluence_tplus2 | True | 0.7541 | True | True |
| eth_syn_mtc_down_le_1p0 | ETH-USD | syn_multitimeframe_trend_confluence_tplus2 | True | 0.7234 | True | True |
| btc_syn_mtc_up_ge_3p0 | BTC-USD | syn_multitimeframe_trend_confluence_tplus2 | True | 0.6885 | True | True |
| btc_syn_early_momentum_divergence_tplus1_up_le_n0p189361 | BTC-USD | syn_early_momentum_divergence_tplus1 | False | 0.8000 | False | False |
| eth_syn_early_momentum_divergence_tplus1_up_le_n0p177442 | ETH-USD | syn_early_momentum_divergence_tplus1 | False | 0.7667 | False | True |
| eth_syn_window_edge_57to01_nonrolling_up_ge_0p0719108856 | ETH-USD | syn_window_edge_57to01_eth_nonrolling_tplus2 | False | 0.7436 | False | True |
| eth_syn_rsi_velocity_5m_3bar_z20_up_ge_1p514696 | ETH-USD | syn_rsi_velocity_5m_3bar_z20 | False | 0.7368 | False | True |
| btc_syn_rsi_velocity_5m_3bar_z20_up_ge_1p489539 | BTC-USD | syn_rsi_velocity_5m_3bar_z20 | False | 0.7143 | False | True |
| btc_syn_rsi_velocity_5m_3bar_z20_down_le_n1p432481 | BTC-USD | syn_rsi_velocity_5m_3bar_z20 | False | 0.6923 | False | True |
| eth_syn_oi_funding_impulse_tplus2_up_le_n1p100426 | ETH-USD | syn_oi_funding_impulse_tplus2 | False | 0.6875 | False | False |
| btc_syn_mtc_down_le_1p0 | BTC-USD | syn_multitimeframe_trend_confluence_tplus2 | False | 0.6809 | False | True |
| btc_syn_cvd_div_15m5_up_le_n2p6735821664 | BTC-USD | syn_cvd_price_divergence_velocity_15m5_tplus2 | False | 0.6667 | False | False |
| eth_syn_window_edge_57to01_nonrolling_down_le_n0p0639929142 | ETH-USD | syn_window_edge_57to01_eth_nonrolling_tplus2 | False | 0.6471 | False | True |
| btc_syn_cvd_div_15m5_down_ge_2p9800626295 | BTC-USD | syn_cvd_price_divergence_velocity_15m5_tplus2 | False | 0.6364 | False | False |
| eth_syn_mtf_signed_efficiency_ratio_down_ge_0p335248 | ETH-USD | syn_mtf_signed_efficiency_ratio_5m12_15m8 | False | 0.6364 | False | False |
| btc_syn_early_momentum_divergence_tplus1_down_ge_0p094863 | BTC-USD | syn_early_momentum_divergence_tplus1 | False | 0.6337 | False | True |
| eth_syn_rsi_velocity_5m_3bar_z20_down_le_n1p625252 | ETH-USD | syn_rsi_velocity_5m_3bar_z20 | False | 0.6316 | False | True |
| eth_syn_cvd_div_15m5_down_ge_1p7811307823 | ETH-USD | syn_cvd_price_divergence_velocity_15m5_tplus2 | False | 0.6111 | False | True |
| eth_syn_early_momentum_divergence_tplus1_down_ge_0p366086 | ETH-USD | syn_early_momentum_divergence_tplus1 | False | 0.6000 | False | False |
| btc_syn_early_impulse_liq_align_tplus2_down_ge_1p205976 | BTC-USD | syn_early_impulse_liq_align_tplus2 | False | 0.5556 | False | True |

## Aggregate

- Rules evaluated: `23`
- Recommended active: `3`
- Recommended inactive: `20`

Source run: `/Users/vitolo/Desktop/projects/poly/scripts/output/signal_integrity/20260212T134921Z`
