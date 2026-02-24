# TRAINING_SCHEMA

```yaml
schema: training
generated_at_utc: 2026-02-09T19:43:31Z
server_version: 17.6
database: postgres
```

## Purpose
Historical ML feature engineering layer.

Contains multi-year spot OHLCV data and enriched indicator tables for model training.
This schema is primarily batch-populated and is not the real-time ingestion path.

## Uniqueness
- Large historical datasets (`spot_1m`, `spot_15m`, `spot_1h`) with consistent primary keys by (symbol, ts/open_time).
- Wide indicator-enriched tables (`spot_15m_indicators`, `spot_1h_indicators`).
- Curated training-ready tables (`unified_15m`, `unified_1h`) and pattern signals (`synthetic_features`).
- Reserved-but-empty Polymarket feature tables (planned integration).

## Update Mechanics
- Historical tables are populated via offline/batch loads (not by the live streamer).
- No training-schema stored functions are currently defined; transformations appear to be external/script-driven.

## Objects (TLDR)
| tables | views | functions | triggers_calling_schema_fns | partitions |
|---|---|---|---|---|
| 17 | 0 | 0 | 0 | 3 |

## Tables With Data
| table | kind | est_rows (n_live_tup) | size |
|---|---|---|---|
| spot_1m | table | 4549681 | 1006.5MB |
| spot_15m_indicators | table | 633987 | 573.1MB |
| spot_15m | table | 633984 | 265.3MB |
| unified_15m | table | 633981 | 793.4MB |
| spot_1h | table | 158506 | 86.4MB |
| spot_1h_indicators | table | 158506 | 143.4MB |
| unified_1h | table | 158503 | 198.4MB |
| synthetic_features | table | 153730 | 45.2MB |
| readme | table | 25 | 136.0KB |

## Tables Without Data (Est Rows = 0)
| table | kind |
|---|---|
| event_labels | table |
| feature_matrix | table |
| polymarket_15m_agg | table |
| polymarket_oracle | table |
| polymarket_ticks | partitioned_table |
| polymarket_ticks_btc | table |
| polymarket_ticks_eth | table |
| polymarket_ticks_sol | table |

## Partitions
| parent | child | bound | est_rows | size |
|---|---|---|---|---|
| polymarket_ticks | polymarket_ticks_btc | FOR VALUES IN ('BTC') | 0 | 64.0KB |
| polymarket_ticks | polymarket_ticks_eth | FOR VALUES IN ('ETH') | 0 | 64.0KB |
| polymarket_ticks | polymarket_ticks_sol | FOR VALUES IN ('SOL') | 0 | 64.0KB |

## Column Reference (Populated Tables Only)
### training.readme

| column | data_type | nullable | default |
|---|---|---|---|
| id | integer | NO | nextval('training.readme_id_seq'::regclass) |
| entry_type | text | NO |  |
| title | text | NO |  |
| content | text | NO |  |
| context | text | YES |  |
| tags | ARRAY | YES |  |
| created_by | text | YES | 'claude'::text |
| created_at | timestamp with time zone | YES | now() |
| updated_at | timestamp with time zone | YES | now() |

### training.spot_15m

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| open | double precision | YES |  |
| high | double precision | YES |  |
| low | double precision | YES |  |
| close | double precision | YES |  |
| volume | double precision | YES |  |
| close_time | timestamp with time zone | YES |  |
| quote_volume | double precision | YES |  |
| num_trades | bigint | YES |  |
| taker_buy_base_vol | double precision | YES |  |
| taker_buy_quote_vol | double precision | YES |  |
| label | text | YES |  |
| pct_change | double precision | YES |  |
| pct_change_zscore | double precision | YES |  |
| high_low_range | double precision | YES |  |
| upper_wick_pct | double precision | YES |  |
| lower_wick_pct | double precision | YES |  |

### training.spot_15m_indicators

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| sma_9 | double precision | YES |  |
| sma_20 | double precision | YES |  |
| sma_50 | double precision | YES |  |
| sma_200 | double precision | YES |  |
| ema_9 | double precision | YES |  |
| ema_12 | double precision | YES |  |
| ema_21 | double precision | YES |  |
| ema_26 | double precision | YES |  |
| ema_50 | double precision | YES |  |
| ema_200 | double precision | YES |  |
| wma_9 | double precision | YES |  |
| wma_21 | double precision | YES |  |
| hma_9 | double precision | YES |  |
| hma_21 | double precision | YES |  |
| vwma_9 | double precision | YES |  |
| vwma_20 | double precision | YES |  |
| rsi_7 | double precision | YES |  |
| rsi_14 | double precision | YES |  |
| rsi_21 | double precision | YES |  |
| stoch_k_5 | double precision | YES |  |
| stoch_d_5 | double precision | YES |  |
| stoch_k_14 | double precision | YES |  |
| stoch_d_14 | double precision | YES |  |
| stoch_rsi_k | double precision | YES |  |
| stoch_rsi_d | double precision | YES |  |
| cci_20 | double precision | YES |  |
| williams_r_14 | double precision | YES |  |
| mfi_14 | double precision | YES |  |
| momentum_10 | double precision | YES |  |
| roc_9 | double precision | YES |  |
| roc_12 | double precision | YES |  |
| macd_line | double precision | YES |  |
| macd_signal | double precision | YES |  |
| macd_hist | double precision | YES |  |
| macd_fast_line | double precision | YES |  |
| macd_fast_signal | double precision | YES |  |
| macd_fast_hist | double precision | YES |  |
| adx_14 | double precision | YES |  |
| plus_di_14 | double precision | YES |  |
| minus_di_14 | double precision | YES |  |
| adx_20 | double precision | YES |  |
| plus_di_20 | double precision | YES |  |
| minus_di_20 | double precision | YES |  |
| aroon_up_14 | double precision | YES |  |
| aroon_down_14 | double precision | YES |  |
| aroon_up_25 | double precision | YES |  |
| aroon_down_25 | double precision | YES |  |
| psar | double precision | YES |  |
| supertrend_10_3 | double precision | YES |  |
| supertrend_dir_10_3 | integer | YES |  |
| supertrend_7_2 | double precision | YES |  |
| supertrend_dir_7_2 | integer | YES |  |
| vortex_plus_14 | double precision | YES |  |
| vortex_minus_14 | double precision | YES |  |
| atr_7 | double precision | YES |  |
| atr_14 | double precision | YES |  |
| atr_21 | double precision | YES |  |
| bb_upper_20 | double precision | YES |  |
| bb_middle_20 | double precision | YES |  |
| bb_lower_20 | double precision | YES |  |
| bb_width_20 | double precision | YES |  |
| bb_upper_20_wide | double precision | YES |  |
| bb_lower_20_wide | double precision | YES |  |
| donchian_upper_20 | double precision | YES |  |
| donchian_lower_20 | double precision | YES |  |
| donchian_mid_20 | double precision | YES |  |
| keltner_upper | double precision | YES |  |
| keltner_middle | double precision | YES |  |
| keltner_lower | double precision | YES |  |
| rvi_10 | double precision | YES |  |
| ulcer_14 | double precision | YES |  |
| obv | double precision | YES |  |
| cvd_50 | double precision | YES |  |
| cvd_100 | double precision | YES |  |
| cmf_10 | double precision | YES |  |
| cmf_20 | double precision | YES |  |
| adl | double precision | YES |  |
| pvt | double precision | YES |  |
| vwap_50 | double precision | YES |  |
| vwap_96 | double precision | YES |  |
| force_index_13 | double precision | YES |  |
| eom_14 | double precision | YES |  |
| bop_14 | double precision | YES |  |
| ao | double precision | YES |  |
| ichimoku_tenkan | double precision | YES |  |
| ichimoku_kijun | double precision | YES |  |
| ichimoku_senkou_a | double precision | YES |  |
| ichimoku_senkou_b | double precision | YES |  |
| ichimoku_chikou | double precision | YES |  |
| linreg_14 | double precision | YES |  |
| linreg_slope_14 | double precision | YES |  |
| linreg_20 | double precision | YES |  |
| linreg_slope_20 | double precision | YES |  |
| pivot | double precision | YES |  |
| pivot_r1 | double precision | YES |  |
| pivot_r2 | double precision | YES |  |
| pivot_s1 | double precision | YES |  |
| pivot_s2 | double precision | YES |  |
| uo | double precision | YES |  |
| buy_pressure_ratio | double precision | YES |  |
| trade_intensity | double precision | YES |  |
| avg_trade_size | double precision | YES |  |

### training.spot_1h

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| open | double precision | YES |  |
| high | double precision | YES |  |
| low | double precision | YES |  |
| close | double precision | YES |  |
| volume | double precision | YES |  |
| close_time | timestamp with time zone | YES |  |
| quote_volume | double precision | YES |  |
| num_trades | bigint | YES |  |
| taker_buy_base_vol | double precision | YES |  |
| taker_buy_quote_vol | double precision | YES |  |
| label | text | YES |  |
| pct_change | double precision | YES |  |
| pct_change_zscore | double precision | YES |  |
| high_low_range | double precision | YES |  |
| upper_wick_pct | double precision | YES |  |
| lower_wick_pct | double precision | YES |  |

### training.spot_1h_indicators

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| sma_9 | double precision | YES |  |
| sma_20 | double precision | YES |  |
| sma_50 | double precision | YES |  |
| sma_200 | double precision | YES |  |
| ema_9 | double precision | YES |  |
| ema_12 | double precision | YES |  |
| ema_21 | double precision | YES |  |
| ema_26 | double precision | YES |  |
| ema_50 | double precision | YES |  |
| ema_200 | double precision | YES |  |
| wma_9 | double precision | YES |  |
| wma_21 | double precision | YES |  |
| hma_9 | double precision | YES |  |
| hma_21 | double precision | YES |  |
| vwma_9 | double precision | YES |  |
| vwma_20 | double precision | YES |  |
| rsi_7 | double precision | YES |  |
| rsi_14 | double precision | YES |  |
| rsi_21 | double precision | YES |  |
| stoch_k_5 | double precision | YES |  |
| stoch_d_5 | double precision | YES |  |
| stoch_k_14 | double precision | YES |  |
| stoch_d_14 | double precision | YES |  |
| stoch_rsi_k | double precision | YES |  |
| stoch_rsi_d | double precision | YES |  |
| cci_20 | double precision | YES |  |
| williams_r_14 | double precision | YES |  |
| mfi_14 | double precision | YES |  |
| momentum_10 | double precision | YES |  |
| roc_9 | double precision | YES |  |
| roc_12 | double precision | YES |  |
| macd_line | double precision | YES |  |
| macd_signal | double precision | YES |  |
| macd_hist | double precision | YES |  |
| macd_fast_line | double precision | YES |  |
| macd_fast_signal | double precision | YES |  |
| macd_fast_hist | double precision | YES |  |
| adx_14 | double precision | YES |  |
| plus_di_14 | double precision | YES |  |
| minus_di_14 | double precision | YES |  |
| adx_20 | double precision | YES |  |
| plus_di_20 | double precision | YES |  |
| minus_di_20 | double precision | YES |  |
| aroon_up_14 | double precision | YES |  |
| aroon_down_14 | double precision | YES |  |
| aroon_up_25 | double precision | YES |  |
| aroon_down_25 | double precision | YES |  |
| psar | double precision | YES |  |
| supertrend_10_3 | double precision | YES |  |
| supertrend_dir_10_3 | integer | YES |  |
| supertrend_7_2 | double precision | YES |  |
| supertrend_dir_7_2 | integer | YES |  |
| vortex_plus_14 | double precision | YES |  |
| vortex_minus_14 | double precision | YES |  |
| atr_7 | double precision | YES |  |
| atr_14 | double precision | YES |  |
| atr_21 | double precision | YES |  |
| bb_upper_20 | double precision | YES |  |
| bb_middle_20 | double precision | YES |  |
| bb_lower_20 | double precision | YES |  |
| bb_width_20 | double precision | YES |  |
| bb_upper_20_wide | double precision | YES |  |
| bb_lower_20_wide | double precision | YES |  |
| donchian_upper_20 | double precision | YES |  |
| donchian_lower_20 | double precision | YES |  |
| donchian_mid_20 | double precision | YES |  |
| donchian_upper_55 | double precision | YES |  |
| donchian_lower_55 | double precision | YES |  |
| donchian_mid_55 | double precision | YES |  |
| keltner_upper | double precision | YES |  |
| keltner_middle | double precision | YES |  |
| keltner_lower | double precision | YES |  |
| rvi_10 | double precision | YES |  |
| ulcer_14 | double precision | YES |  |
| obv | double precision | YES |  |
| cvd_50 | double precision | YES |  |
| cvd_100 | double precision | YES |  |
| cmf_10 | double precision | YES |  |
| cmf_20 | double precision | YES |  |
| adl | double precision | YES |  |
| pvt | double precision | YES |  |
| vwap_24 | double precision | YES |  |
| force_index_13 | double precision | YES |  |
| eom_14 | double precision | YES |  |
| bop_14 | double precision | YES |  |
| ao | double precision | YES |  |
| ichimoku_tenkan | double precision | YES |  |
| ichimoku_kijun | double precision | YES |  |
| ichimoku_senkou_a | double precision | YES |  |
| ichimoku_senkou_b | double precision | YES |  |
| ichimoku_chikou | double precision | YES |  |
| linreg_14 | double precision | YES |  |
| linreg_slope_14 | double precision | YES |  |
| pivot | double precision | YES |  |
| pivot_r1 | double precision | YES |  |
| pivot_r2 | double precision | YES |  |
| pivot_s1 | double precision | YES |  |
| pivot_s2 | double precision | YES |  |
| uo | double precision | YES |  |
| buy_pressure_ratio | double precision | YES |  |
| trade_intensity | double precision | YES |  |
| avg_trade_size | double precision | YES |  |

### training.spot_1m

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| ts | timestamp with time zone | NO |  |
| open | double precision | YES |  |
| high | double precision | YES |  |
| low | double precision | YES |  |
| close | double precision | YES |  |
| volume | double precision | YES |  |
| ma_20 | double precision | YES |  |
| ma_50 | double precision | YES |  |
| ma_200 | double precision | YES |  |
| rsi | double precision | YES |  |
| macd | double precision | YES |  |
| macd_signal | double precision | YES |  |
| bb_upper | double precision | YES |  |
| bb_middle | double precision | YES |  |
| bb_lower | double precision | YES |  |
| stoch_k | double precision | YES |  |
| stoch_d | double precision | YES |  |
| adx | double precision | YES |  |
| atr | double precision | YES |  |
| obv | double precision | YES |  |
| vwap | double precision | YES |  |
| trendline_support | double precision | YES |  |
| trendline_resistance | double precision | YES |  |

### training.synthetic_features

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| label | text | YES |  |
| label_binary | integer | YES |  |
| pct_change | double precision | YES |  |
| supertrend_bull_confirmed | integer | YES | 0 |
| supertrend_bear_confirmed | integer | YES | 0 |
| vwap_bull_reject | integer | YES | 0 |
| vwap_bear_reject | integer | YES | 0 |
| bb_breakout_upper | double precision | YES |  |
| bb_breakout_lower | double precision | YES |  |
| strong_breakout_up | integer | YES | 0 |
| strong_breakout_down | integer | YES | 0 |
| above_cloud | integer | YES | 0 |
| below_cloud | integer | YES | 0 |
| ichimoku_bull_setup | integer | YES | 0 |
| ichimoku_bear_setup | integer | YES | 0 |
| macd_accel_up | integer | YES | 0 |
| macd_accel_down | integer | YES | 0 |
| macd_hist_roc | double precision | YES |  |
| in_squeeze | integer | YES | 0 |
| squeeze_break_up | integer | YES | 0 |
| squeeze_break_down | integer | YES | 0 |
| composite_obos | double precision | YES |  |
| extreme_overbought | integer | YES | 0 |
| extreme_oversold | integer | YES | 0 |
| cmf_cvd_bull_confluence | integer | YES | 0 |
| cmf_cvd_bear_confluence | integer | YES | 0 |
| trend_regime_bull | integer | YES | 0 |
| trend_regime_bear | integer | YES | 0 |
| trend_regime_weak | integer | YES | 0 |
| trend_strength | double precision | YES |  |
| next_label | text | YES |  |
| next_label_binary | integer | YES |  |
| next_pct_change | double precision | YES |  |

### training.unified_15m

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| open | double precision | YES |  |
| high | double precision | YES |  |
| low | double precision | YES |  |
| close | double precision | YES |  |
| volume | double precision | YES |  |
| label | text | YES |  |
| pct_change | double precision | YES |  |
| is_btc | integer | YES |  |
| is_eth | integer | YES |  |
| is_sol | integer | YES |  |
| next_label | text | YES |  |
| next_pct_change | double precision | YES |  |
| rsi_14 | double precision | YES |  |
| rsi_7 | double precision | YES |  |
| rsi_21 | double precision | YES |  |
| macd_line | double precision | YES |  |
| macd_signal | double precision | YES |  |
| macd_hist | double precision | YES |  |
| adx_14 | double precision | YES |  |
| plus_di_14 | double precision | YES |  |
| minus_di_14 | double precision | YES |  |
| supertrend_10_3 | double precision | YES |  |
| supertrend_dir_10_3 | integer | YES |  |
| stoch_k_14 | double precision | YES |  |
| stoch_d_14 | double precision | YES |  |
| stoch_rsi_k | double precision | YES |  |
| stoch_rsi_d | double precision | YES |  |
| cci_20 | double precision | YES |  |
| williams_r_14 | double precision | YES |  |
| mfi_14 | double precision | YES |  |
| bb_upper_20 | double precision | YES |  |
| bb_middle_20 | double precision | YES |  |
| bb_lower_20 | double precision | YES |  |
| bb_width_20 | double precision | YES |  |
| keltner_upper | double precision | YES |  |
| keltner_middle | double precision | YES |  |
| keltner_lower | double precision | YES |  |
| atr_14 | double precision | YES |  |
| atr_7 | double precision | YES |  |
| atr_21 | double precision | YES |  |
| ema_9 | double precision | YES |  |
| ema_21 | double precision | YES |  |
| ema_50 | double precision | YES |  |
| ema_200 | double precision | YES |  |
| sma_20 | double precision | YES |  |
| sma_50 | double precision | YES |  |
| sma_200 | double precision | YES |  |
| obv | double precision | YES |  |
| cvd_50 | double precision | YES |  |
| cvd_100 | double precision | YES |  |
| cmf_20 | double precision | YES |  |
| cmf_10 | double precision | YES |  |
| vwap_50 | double precision | YES |  |
| vwap_96 | double precision | YES |  |
| ichimoku_tenkan | double precision | YES |  |
| ichimoku_kijun | double precision | YES |  |
| ichimoku_senkou_a | double precision | YES |  |
| ichimoku_senkou_b | double precision | YES |  |
| momentum_10 | double precision | YES |  |
| roc_12 | double precision | YES |  |
| linreg_14 | double precision | YES |  |
| linreg_slope_14 | double precision | YES |  |
| pivot | double precision | YES |  |
| pivot_r1 | double precision | YES |  |
| pivot_s1 | double precision | YES |  |
| uo | double precision | YES |  |
| next_label_binary | integer | YES |  |
| syn_extreme_oversold | integer | YES | 0 |
| syn_extreme_overbought | integer | YES | 0 |
| syn_strong_breakout_down | integer | YES | 0 |
| syn_strong_breakout_up | integer | YES | 0 |
| syn_macd_accel_up | integer | YES | 0 |
| syn_macd_accel_down | integer | YES | 0 |
| syn_cmf_cvd_bear_confluence | integer | YES | 0 |
| syn_vwap_bear_reject | integer | YES | 0 |

### training.unified_1h

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| open_time | timestamp with time zone | NO |  |
| open | double precision | YES |  |
| high | double precision | YES |  |
| low | double precision | YES |  |
| close | double precision | YES |  |
| volume | double precision | YES |  |
| label | text | YES |  |
| pct_change | double precision | YES |  |
| is_btc | integer | YES |  |
| is_eth | integer | YES |  |
| is_sol | integer | YES |  |
| next_label | text | YES |  |
| next_pct_change | double precision | YES |  |
| rsi_14 | double precision | YES |  |
| rsi_7 | double precision | YES |  |
| rsi_21 | double precision | YES |  |
| macd_line | double precision | YES |  |
| macd_signal | double precision | YES |  |
| macd_hist | double precision | YES |  |
| adx_14 | double precision | YES |  |
| plus_di_14 | double precision | YES |  |
| minus_di_14 | double precision | YES |  |
| supertrend_10_3 | double precision | YES |  |
| supertrend_dir_10_3 | integer | YES |  |
| stoch_k_14 | double precision | YES |  |
| stoch_d_14 | double precision | YES |  |
| stoch_rsi_k | double precision | YES |  |
| stoch_rsi_d | double precision | YES |  |
| cci_20 | double precision | YES |  |
| williams_r_14 | double precision | YES |  |
| mfi_14 | double precision | YES |  |
| bb_upper_20 | double precision | YES |  |
| bb_middle_20 | double precision | YES |  |
| bb_lower_20 | double precision | YES |  |
| bb_width_20 | double precision | YES |  |
| keltner_upper | double precision | YES |  |
| keltner_middle | double precision | YES |  |
| keltner_lower | double precision | YES |  |
| atr_14 | double precision | YES |  |
| atr_7 | double precision | YES |  |
| atr_21 | double precision | YES |  |
| ema_9 | double precision | YES |  |
| ema_21 | double precision | YES |  |
| ema_50 | double precision | YES |  |
| ema_200 | double precision | YES |  |
| sma_20 | double precision | YES |  |
| sma_50 | double precision | YES |  |
| sma_200 | double precision | YES |  |
| obv | double precision | YES |  |
| cvd_50 | double precision | YES |  |
| cvd_100 | double precision | YES |  |
| cmf_20 | double precision | YES |  |
| cmf_10 | double precision | YES |  |
| vwap_24 | double precision | YES |  |
| ichimoku_tenkan | double precision | YES |  |
| ichimoku_kijun | double precision | YES |  |
| ichimoku_senkou_a | double precision | YES |  |
| ichimoku_senkou_b | double precision | YES |  |
| momentum_10 | double precision | YES |  |
| roc_12 | double precision | YES |  |
| linreg_14 | double precision | YES |  |
| linreg_slope_14 | double precision | YES |  |
| pivot | double precision | YES |  |
| pivot_r1 | double precision | YES |  |
| pivot_s1 | double precision | YES |  |
| uo | double precision | YES |  |
| next_label_binary | integer | YES |  |
| syn_extreme_oversold | integer | YES | 0 |
| syn_extreme_overbought | integer | YES | 0 |
| syn_strong_breakout_down | integer | YES | 0 |
| syn_strong_breakout_up | integer | YES | 0 |
| syn_macd_accel_up | integer | YES | 0 |
| syn_macd_accel_down | integer | YES | 0 |
| syn_cmf_cvd_bear_confluence | integer | YES | 0 |
| syn_vwap_bear_reject | integer | YES | 0 |
