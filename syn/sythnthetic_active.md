# Synthetic Active

This document lists the currently active synthetic indicators in `indicators.synthetic_indicator_configs`, the formulas used to compute them, their upstream dependencies, and the active codex decision logic currently applied.

## Global Decision Logic (Codex Signals)
- Signal emission table: `indicators.codex_signals`
- Rules table: `indicators.codex_signal_rules`
- Runtime: evaluate rule conditions at each 15m event bucket (`t0`) once decision minute is available (`t0+2m` for codex queue processing).
- A rule fires when its condition matches (`v1 >= threshold` or `v1 <= threshold`).
- `signals_passed` = count of fired rules for the same `(pair, bucket_time, prediction)`.

---

## 1) `syn_mtf_signed_efficiency_ratio_5m12_15m8`
- Name: `mtf_signed_efficiency_ratio`
- Decision phase: `t_plus_1m`
- Formula:
  - `ER_5m = (close_last - close_12_back) / sum(abs(diff_5m_closes), 11 steps)`
  - `ER_15m = (close_last - close_8_back) / sum(abs(diff_15m_closes), 7 steps)`
  - `v1 = ER_5m * ER_15m`
- Upstream inputs:
  - `indicators.ohlcv_5m.close`
  - `indicators.ohlcv_15m.close`
- Active codex decision rules:
  - `ETH-USD`: `v1 >= 0.335248` -> `DOWN` (base accuracy `62.50%`)
  - `SOL-USD`: `v1 >= 0.435057` -> `DOWN` (base accuracy `67.65%`)

## 2) `syn_rsi_velocity_5m_3bar_z20`
- Name: `rsi_velocity_5m`
- Decision phase: `t_plus_1m`
- Formula:
  - `raw = rsi_7_5m[t] - rsi_7_5m[t-3 bars]`
  - `mu = rolling_mean(raw, 20 samples)`
  - `sd_used = max(rolling_std(raw, 20 samples), 0.5)`
  - `v1 = z_velocity = (raw - mu) / sd_used`
- Upstream inputs:
  - `indicators.indicator_values(config_id='rsi_7_5m').v1`
  - `indicators.indicator_values(config_id='rsi_14_1h').v1`
- Active codex decision rules:
  - `BTC-USD`: `v1 >= 1.489539` -> `UP` (`65.62%`)
  - `BTC-USD`: `v1 <= -1.432481` -> `DOWN` (`65.52%`)
  - `ETH-USD`: `v1 >= 1.514696` -> `UP` (`63.73%`)
  - `ETH-USD`: `v1 <= -1.625252` -> `DOWN` (`69.41%`)
  - `SOL-USD`: `v1 >= 1.604583` -> `UP` (`65.88%`)
  - `SOL-USD`: `v1 <= -1.525095` -> `DOWN` (`64.21%`)

## 3) `syn_early_impulse_liq_align_tplus2`
- Name: `early_impulse_liquidity_alignment_2m`
- Decision phase: `t_plus_2m`
- Formula:
  - `r_early = ln(close_1m[t0+2m] / open_15m[t0])`
  - `atr_pct = atr_14_1m[t0+2m] / close_1m[t0+2m]`
  - `r_vol = r_early / atr_pct`
  - `z_r = zscore(r_vol, trailing 720x1m)`
  - `liq_align = 0.60*tanh(imbalance) + 0.30*tanh(depth_skew) - 0.20*tanh(slippage_skew) - 0.30*tanh(spread_z)`
  - `v1 = z_r * liq_align`
- Upstream inputs:
  - `indicators.ohlcv_15m.open`
  - `indicators.ohlcv_1m.close`
  - `indicators.indicator_values(config_id='atr_14_1m').v1`
  - `indicators.order_book_indicators` (`imbalance`, `bid_depth_25bps`, `ask_depth_25bps`, `slippage_buy_100`, `slippage_sell_100`, `spread_pct`)
- Active codex decision rules:
  - `BTC-USD`: `v1 >= 1.205976` -> `DOWN` (`69.33%`)
  - `ETH-USD`: `v1 >= 1.289645` -> `DOWN` (`62.34%`)
  - `SOL-USD`: `v1 <= -0.567129` -> `DOWN` (`61.32%`)

## 4) `syn_oi_funding_impulse_tplus2`
- Name: `oi_funding_impulse_confirmation_2m`
- Decision phase: `t_plus_2m`
- Formula:
  - Same early impulse normalization to get `z_r`
  - `oi_support = 0.7*z(oi_acceleration) + 0.3*z(oi_roc_1h)`
  - `crowding = 0.6*z(funding_oi_pressure) + 0.4*z(basis_pct)`
  - `v1 = z_r * tanh(oi_support) - 0.50 * abs(z_r) * tanh(max(crowding, 0)) * sign(z_r)`
- Upstream inputs:
  - `indicators.ohlcv_15m.open`
  - `indicators.ohlcv_1m.close`
  - `indicators.indicator_values(config_id='atr_14_1m').v1`
  - `indicators.oi_features` (`oi_acceleration`, `oi_roc_1h`, `funding_oi_pressure`, `basis_pct`)
- Active codex decision rules:
  - `BTC-USD`: `v1 >= 1.331442` -> `DOWN` (`65.38%`)
  - `ETH-USD`: `v1 <= -1.100426` -> `UP` (`63.10%`)
  - `SOL-USD`: `v1 >= 1.606966` -> `DOWN` (`72.73%`)

## 5) `syn_early_momentum_divergence_tplus1`
- Name: `early_momentum_divergence_score`
- Decision phase: `t_plus_1m`
- Formula:
  - `price_roc = (close_1m[t0+1m] - max(close_1m[t0-3m..t0-1m])) / max(close_1m[t0-3m..t0-1m])`
  - `rsi_roc = (rsi_7_5m[t0] - rsi_7_5m[t0-5m]) / 100`
  - `macd_accel = macd_hist_5m[t0] - macd_hist_5m[t0-5m]`
  - `cvd_roc = (cvd_20_1m[t0+1m] - cvd_20_1m[t0-4m]) / abs(cvd_20_1m[t0-4m])`
  - `indicator_mom = (rsi_roc + 0.5*sign(macd_accel) + cvd_roc) / 2.5`
  - `v1 = (indicator_mom - sign(price_roc)) * abs(price_roc) * 100`
- Upstream inputs:
  - `indicators.ohlcv_1m.close`
  - `indicators.indicator_values(config_id='rsi_7_5m').v1`
  - `indicators.indicator_values(config_id='macd_8_17_9_5m').v3`
  - `indicators.indicator_values(config_id='cvd_20_1m').v1`
- Active codex decision rules:
  - `BTC-USD`: `v1 <= -0.189361` -> `UP` (`64.00%`)
  - `BTC-USD`: `v1 >= 0.094863` -> `DOWN` (`64.41%`)
  - `ETH-USD`: `v1 <= -0.177442` -> `UP` (`65.73%`)
  - `ETH-USD`: `v1 >= 0.366086` -> `DOWN` (`66.08%`)
  - `SOL-USD`: `v1 <= -0.384006` -> `UP` (`66.67%`)
  - `SOL-USD`: `v1 >= 0.645655` -> `DOWN` (`63.16%`)

## 6) `syn_order_flow_accel_regime_tplus2`
- Name: `order_flow_acceleration_regime`
- Decision phase: `t_plus_2m`
- Formula:
  - `cvd_accel = (cvd_50_5m[t0]-cvd_50_5m[t0-5m]) - (cvd_50_5m[t0-5m]-cvd_50_5m[t0-10m])`
  - `ob_pressure_now = (bid25 - ask25)/(bid25 + ask25)`
  - `ob_pressure_roc = ob_pressure_now - ob_pressure_prev`
  - `vol_surge = (vol_15m[t0] - avg(vol_15m[t0-15m,t0-30m,t0-45m])) / avg(...)`
  - `flow_mom = 0.4*cvd_accel + 0.3*ob_pressure_roc + 0.3*vol_surge`
  - `price_roc_2m = (close_1m[t0+2m] - close_1m[t0]) / close_1m[t0]`
  - `v1 = flow_mom * sign(price_roc_2m) * 10`
- Upstream inputs:
  - `indicators.indicator_values(config_id='cvd_50_5m').v1`
  - `indicators.order_book_indicators` (`bid_depth_25bps`, `ask_depth_25bps`, `depth_ratio`)
  - `indicators.ohlcv_15m.volume`
  - `indicators.ohlcv_1m.close`
- Active codex decision rules:
  - None currently active for this config (`>=60%` threshold rules were not seeded for this one).

## 7) `syn_window_edge_57to01_eth_nonrolling_tplus2`
- Name: `window_edge_57to01_nonrolling_eth`
- Decision phase: `t_plus_2m`
- Scope: ETH only (`p_pair='ETH-USD'`)
- Formula:
  - `v1 = pct_diff_57_to_01 = ((close_1m[t0+1m] - open_1m[t0-3m]) / open_1m[t0-3m]) * 100`
  - `v2 = direction_code`:
    - `1` if `v1 > 0.0719108856117475`
    - `-1` if `v1 < -0.0639929141611394`
    - `0` otherwise
  - `v3 = selected_base_accuracy`:
    - `0.676471` when UP threshold passes
    - `0.592593` when DOWN threshold passes
- Upstream inputs:
  - `indicators.ohlcv_1m.open` (`t0-3m`)
  - `indicators.ohlcv_1m.close` (`t0+1m`)
- Active codex decision rules:
  - `ETH-USD`: `v1 >= 0.0719108856117475` -> `UP` (`67.6471%`)
  - `ETH-USD`: `v1 <= -0.0639929141611394` -> `DOWN` (`59.2593%`)

---

## Active Count Snapshot
- Active synthetic configs: `7`
- Active codex rules tied to synthetic configs: `22`
