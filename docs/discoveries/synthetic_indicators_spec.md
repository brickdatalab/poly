# Synthetic Indicators Specification (Indicators Schema)

## Scope
This spec defines six synthetic indicators that are computed from existing indicators/market tables without modifying existing workflows. All synthetics are computed at 15-minute event boundaries (`t0` in `:00/:15/:30/:45`) and written into a separate synthetic subsystem.

## Standard Output Contract
Each synthetic indicator writes into `synthetic_indicator_values` with:
- `v1`: primary synthetic signal score used for filtering.
- `v2..v5`: key diagnostic components for explainability/debugging.
- `decision_phase`: when the score is legal to consume (`t_plus_1m` or `t_plus_2m`).
- `quality_flags`: JSONB diagnostics (`missing_inputs`, `low_history`, `stale_orderbook`, etc.).

---

## 1) mtf_signed_efficiency_ratio
- `config_id`: `syn_mtf_signed_efficiency_ratio_5m12_15m8`
- `decision_phase`: `t_plus_1m`
- `lookback_requirements`:
  - 5m ER: 12 candles
  - 15m ER: 8 candles
- `source_columns`:
  - `indicators.ohlcv_5m.close`
  - `indicators.ohlcv_15m.close`
- `formula_summary`:
  - `ER_5m = (close[t-1]-close[t-12]) / sum(abs(diff close), 11 steps)`
  - `ER_15m = (close[t-1]-close[t-8]) / sum(abs(diff close), 7 steps)`
  - `signal = ER_5m * ER_15m`
- `v_map`:
  - `v1=signal`
  - `v2=er_5m`
  - `v3=er_15m`
  - `v4=abs(er_5m)`
  - `v5=abs(er_15m)`
- `synthetic_indicator_purpose`:
  - Captures whether fast and slow trend efficiency align, conflict, or chop.

## 2) rsi_velocity_5m
- `config_id`: `syn_rsi_velocity_5m_3bar_z20`
- `decision_phase`: `t_plus_1m`
- `lookback_requirements`:
  - `rsi_7_5m` and `rsi_14_1h`
  - trailing 20x5m for z-normalization
- `source_columns`:
  - `indicators.indicator_values(config_id='rsi_7_5m').v1`
  - `indicators.indicator_values(config_id='rsi_14_1h').v1`
- `formula_summary`:
  - `raw = rsi_7_5m[t-1] - rsi_7_5m[t-4]`
  - `z = (raw - mean_20) / max(std_20, 0.5)`
- `v_map`:
  - `v1=z_velocity`
  - `v2=raw_velocity`
  - `v3=rsi_7_5m_last`
  - `v4=rsi_14_1h_last`
  - `v5=rolling_std_used`
- `synthetic_indicator_purpose`:
  - Measures short-horizon RSI acceleration while preserving macro RSI regime context.

## 3) early_impulse_liquidity_alignment_2m
- `config_id`: `syn_early_impulse_liq_align_tplus2`
- `decision_phase`: `t_plus_2m`
- `lookback_requirements`:
  - `t0+2m` 1m close
  - trailing 720x1m z-score windows
  - latest order book snapshot <= `t0+2m` (freshness <=5m)
- `source_columns`:
  - `indicators.ohlcv_15m.open`
  - `indicators.ohlcv_1m.close`
  - `indicators.indicator_values(config_id='atr_14_1m').v1`
  - `indicators.order_book_indicators.{imbalance,bid_depth_25bps,ask_depth_25bps,slippage_buy_100,slippage_sell_100,spread_pct}`
- `formula_summary`:
  - early boundary return normalized by ATR%
  - combined with order-book alignment/skew terms
  - `signal = z_r * liq_align`
- `v_map`:
  - `v1=signal`
  - `v2=z_r`
  - `v3=liq_align`
  - `v4=depth_skew`
  - `v5=spread_z`
- `synthetic_indicator_purpose`:
  - Confirms whether early impulse direction is supported by current liquidity structure.

## 4) oi_funding_impulse_confirmation_2m
- `config_id`: `syn_oi_funding_impulse_tplus2`
- `decision_phase`: `t_plus_2m`
- `lookback_requirements`:
  - `t0+2m` boundary return normalization
  - trailing 96x15m windows for OI/funding z-scores
- `source_columns`:
  - `indicators.ohlcv_15m.open`
  - `indicators.ohlcv_1m.close`
  - `indicators.indicator_values(config_id='atr_14_1m').v1`
  - `indicators.oi_features.{oi_acceleration,oi_roc_1h,funding_oi_pressure,basis_pct}`
- `formula_summary`:
  - normalized early return + OI participation impulse
  - crowding penalty via funding/basis pressure
  - `signal = z_r * tanh(oi_support) - 0.5 * abs(z_r) * tanh(max(crowding,0)) * sign(z_r)`
- `v_map`:
  - `v1=signal`
  - `v2=z_r`
  - `v3=oi_support`
  - `v4=crowding`
  - `v5=oi_acc_z`
- `synthetic_indicator_purpose`:
  - Tests whether early move is backed by participation vs crowded carry.

## 5) early_momentum_divergence_score
- `config_id`: `syn_early_momentum_divergence_tplus1`
- `decision_phase`: `t_plus_1m`
- `lookback_requirements`:
  - 3 prior 1m closes + `t0+1m` close
  - `rsi_7_5m`, `macd_8_17_9_5m.v3`, `cvd_20_1m`
- `source_columns`:
  - `indicators.ohlcv_1m.close`
  - `indicators.indicator_values(config_id='rsi_7_5m').v1`
  - `indicators.indicator_values(config_id='macd_8_17_9_5m').v3`
  - `indicators.indicator_values(config_id='cvd_20_1m').v1`
- `formula_summary`:
  - compares boundary price ROC to internal momentum ROC/acceleration
  - `emds = (indicator_momentum - sign(price_roc_boundary)) * abs(price_roc_boundary) * 100`
- `v_map`:
  - `v1=emds`
  - `v2=price_roc_boundary`
  - `v3=rsi_roc`
  - `v4=macd_accel`
  - `v5=cvd_roc`
- `synthetic_indicator_purpose`:
  - Detects early momentum divergence between price and internals.

## 6) order_flow_acceleration_regime
- `config_id`: `syn_order_flow_accel_regime_tplus2`
- `decision_phase`: `t_plus_2m`
- `lookback_requirements`:
  - 6-candle pre-window context
  - `cvd_50_5m`
  - order-book snapshots around boundary
- `source_columns`:
  - `indicators.indicator_values(config_id='cvd_50_5m').v1`
  - `indicators.order_book_indicators.{imbalance,depth_ratio,bid_depth_25bps,ask_depth_25bps}`
  - `indicators.ohlcv_15m.volume`
  - `indicators.ohlcv_1m.close`
- `formula_summary`:
  - CVD second derivative + order-book pressure ROC + volume surge
  - directional alignment by early price momentum
  - `ofar = flow_momentum * sign(price_roc_2m) * 10`
- `v_map`:
  - `v1=ofar`
  - `v2=cvd_accel`
  - `v3=ob_pressure_roc`
  - `v4=vol_surge`
  - `v5=depth_ratio`
- `synthetic_indicator_purpose`:
  - Captures early order-flow acceleration regime with liquidity confirmation.

---

## Global Notes
- All formulas are no-leakage by construction (no `t0+14m` usage).
- Any missing dependencies write `NULL` signal and a populated `quality_flags` reason.
- Threshold ladders live in config `params`, not hardcoded in compute functions.
