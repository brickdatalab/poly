# INDICATORS_SCHEMA

```yaml
schema: indicators
generated_at_utc: 2026-02-09T19:43:31Z
server_version: 17.6
database: postgres
```

## Purpose
Real-time computation layer for technical indicators.

Consumes 1m OHLCV candles and produces:
- multi-timeframe OHLCV rollups (`ohlcv_5m`..`ohlcv_12h`)
- long-form indicator outputs in weekly partitions (`indicator_values_wYYYY_WW`)
- order book derived indicators (`order_book_indicators`)
- operational metadata (`job_queue`, `computation_log`, `readme`)

## Uniqueness
- Config-driven indicator computation via `indicator_configs` (JSONB params, 156 active configs).
- Long-table design for indicators: `indicator_values(pair, bucket_time, config_id, v1..v5)`.
- Weekly partitioning for `indicator_values` to keep partitions manageable for recent-only queries.
- Separate OHLCV tables per timeframe for query isolation and predictable access paths.

## Update Mechanics
- Trade ingestion happens upstream in `public` and then cascades here via trigger + job queue orchestration.
- `fn_process_new_trade` is a SECURITY DEFINER trigger function used to keep ingestion fast.
- Rollups are performed via `fn_rollup_ohlcv` / `fn_cascade_timeframes` and backfills via `fn_backfill_ohlcv`.
- Indicator computation runs via `fn_compute_all_indicators` and is decoupled through `job_queue`.

## Objects (TLDR)
| tables | views | functions | triggers_calling_schema_fns | partitions |
|---|---|---|---|---|
| 48 | 8 | 55 | 37 | 29 |

## Tables With Data
| table | kind | est_rows (n_live_tup) | size |
|---|---|---|---|
| indicator_values_w2026_05 | table | 635216 | 189.4MB |
| indicator_values_w2026_06 | table | 579166 | 172.7MB |
| indicator_values_w2026_04 | table | 186915 | 56.8MB |
| order_book_indicators | table | 146785 | 57.8MB |
| job_queue | table | 84692 | 27.5MB |
| ohlcv_1m | table | 79600 | 64.7MB |
| ohlcv_5m | table | 15958 | 4.7MB |
| computation_log | table | 14137 | 4.1MB |
| ohlcv_10m | table | 7683 | 2.4MB |
| open_interest | table | 6003 | 3.4MB |
| ohlcv_15m | table | 5325 | 1.7MB |
| oi_features | table | 5166 | 3.0MB |
| temp-table1 | table | 4439 | 9.2MB |
| ohlcv_30m | table | 2562 | 896.0KB |
| ohlcv_45m | table | 1764 | 11.9MB |
| ohlcv_1h | table | 1334 | 520.0KB |
| ohlcv_2h | table | 639 | 312.0KB |
| ohlcv_6h | table | 217 | 136.0KB |
| indicator_configs | table | 156 | 144.0KB |
| ohlcv_12h | table | 108 | 120.0KB |
| readme | table | 39 | 216.0KB |

## Tables Without Data (Est Rows = 0)
| table | kind |
|---|---|
| indicator_values | partitioned_table |
| indicator_values_w2026_03 | table |
| indicator_values_w2026_07 | table |
| indicator_values_w2026_08 | table |
| indicator_values_w2026_09 | table |
| indicator_values_w2026_10 | table |
| indicator_values_w2026_11 | table |
| indicator_values_w2026_12 | table |
| indicator_values_w2026_13 | table |
| indicator_values_w2026_14 | table |
| indicator_values_w2026_15 | table |
| indicator_values_w2026_16 | table |
| indicator_values_w2026_17 | table |
| indicator_values_w2026_18 | table |
| indicator_values_w2026_19 | table |
| indicator_values_w2026_20 | table |
| indicator_values_w2026_21 | table |
| indicator_values_w2026_22 | table |
| indicator_values_w2026_23 | table |
| indicator_values_w2026_24 | table |
| indicator_values_w2026_25 | table |
| indicator_values_w2026_26 | table |
| indicator_values_w2026_27 | table |
| indicator_values_w2026_28 | table |
| indicator_values_w2026_29 | table |
| indicator_values_w2026_30 | table |
| indicator_values_w2026_31 | table |

## Partitions
| parent | child | bound | est_rows | size |
|---|---|---|---|---|
| indicator_values | indicator_values_w2026_03 | FOR VALUES FROM ('2026-01-13 00:00:00+00') TO ('2026-01-20 00:00:00+00') | 0 | 64.0KB |
| indicator_values | indicator_values_w2026_04 | FOR VALUES FROM ('2026-01-20 00:00:00+00') TO ('2026-01-27 00:00:00+00') | 186915 | 56.8MB |
| indicator_values | indicator_values_w2026_05 | FOR VALUES FROM ('2026-01-27 00:00:00+00') TO ('2026-02-03 00:00:00+00') | 635216 | 189.4MB |
| indicator_values | indicator_values_w2026_06 | FOR VALUES FROM ('2026-02-03 00:00:00+00') TO ('2026-02-10 00:00:00+00') | 579166 | 172.7MB |
| indicator_values | indicator_values_w2026_07 | FOR VALUES FROM ('2026-02-10 00:00:00+00') TO ('2026-02-17 00:00:00+00') | 0 | 120.0KB |
| indicator_values | indicator_values_w2026_08 | FOR VALUES FROM ('2026-02-17 00:00:00+00') TO ('2026-02-24 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_09 | FOR VALUES FROM ('2026-02-24 00:00:00+00') TO ('2026-03-03 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_10 | FOR VALUES FROM ('2026-03-03 00:00:00+00') TO ('2026-03-10 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_11 | FOR VALUES FROM ('2026-03-10 00:00:00+00') TO ('2026-03-17 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_12 | FOR VALUES FROM ('2026-03-17 00:00:00+00') TO ('2026-03-24 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_13 | FOR VALUES FROM ('2026-03-24 00:00:00+00') TO ('2026-03-31 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_14 | FOR VALUES FROM ('2026-03-31 00:00:00+00') TO ('2026-04-07 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_15 | FOR VALUES FROM ('2026-04-07 00:00:00+00') TO ('2026-04-14 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_16 | FOR VALUES FROM ('2026-04-14 00:00:00+00') TO ('2026-04-21 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_17 | FOR VALUES FROM ('2026-04-21 00:00:00+00') TO ('2026-04-28 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_18 | FOR VALUES FROM ('2026-04-28 00:00:00+00') TO ('2026-05-05 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_19 | FOR VALUES FROM ('2026-05-05 00:00:00+00') TO ('2026-05-12 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_20 | FOR VALUES FROM ('2026-05-12 00:00:00+00') TO ('2026-05-19 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_21 | FOR VALUES FROM ('2026-05-19 00:00:00+00') TO ('2026-05-26 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_22 | FOR VALUES FROM ('2026-05-26 00:00:00+00') TO ('2026-06-02 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_23 | FOR VALUES FROM ('2026-06-02 00:00:00+00') TO ('2026-06-09 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_24 | FOR VALUES FROM ('2026-06-09 00:00:00+00') TO ('2026-06-16 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_25 | FOR VALUES FROM ('2026-06-16 00:00:00+00') TO ('2026-06-23 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_26 | FOR VALUES FROM ('2026-06-23 00:00:00+00') TO ('2026-06-30 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_27 | FOR VALUES FROM ('2026-06-30 00:00:00+00') TO ('2026-07-07 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_28 | FOR VALUES FROM ('2026-07-07 00:00:00+00') TO ('2026-07-14 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_29 | FOR VALUES FROM ('2026-07-14 00:00:00+00') TO ('2026-07-21 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_30 | FOR VALUES FROM ('2026-07-21 00:00:00+00') TO ('2026-07-28 00:00:00+00') | 0 | 48.0KB |
| indicator_values | indicator_values_w2026_31 | FOR VALUES FROM ('2026-07-28 00:00:00+00') TO ('2026-08-04 00:00:00+00') | 0 | 48.0KB |

## Views
| view | has_rows (best-effort) |
|---|---|
| v_error_summary | false |
| v_model_15m | true |
| v_model_1h | true |
| v_model_1m | true |
| v_model_5m | true |
| v_null_summary | false |
| v_recent_errors | false |
| v_slow_computations | true |

## View Definitions
### indicators.v_error_summary

| column | data_type | nullable |
|---|---|---|
| config_id | text | YES |
| error_count | bigint | YES |
| last_error | timestamp with time zone | YES |
| sample_error | text | YES |

```sql
SELECT config_id,
    count(*) AS error_count,
    max(created_at) AS last_error,
    max(error_message) AS sample_error
   FROM indicators.computation_log
  WHERE status = 'error'::text AND created_at >= (now() - '24:00:00'::interval)
  GROUP BY config_id
  ORDER BY (count(*)) DESC;
```

### indicators.v_model_15m

| column | data_type | nullable |
|---|---|---|
| pair | text | YES |
| bucket_time | timestamp with time zone | YES |
| open | numeric | YES |
| high | numeric | YES |
| low | numeric | YES |
| close | numeric | YES |
| volume | numeric | YES |
| buy_volume | numeric | YES |
| sell_volume | numeric | YES |
| trade_count | integer | YES |
| adl_50 | numeric | YES |
| adx_14 | numeric | YES |
| adx_14_plus_di | numeric | YES |
| adx_14_minus_di | numeric | YES |
| adx_20 | numeric | YES |
| adx_20_plus_di | numeric | YES |
| adx_20_minus_di | numeric | YES |
| aroon_14_up | numeric | YES |
| aroon_14_down | numeric | YES |
| aroon_14_osc | numeric | YES |
| aroon_25_up | numeric | YES |
| aroon_25_down | numeric | YES |
| aroon_25_osc | numeric | YES |
| atr_14 | numeric | YES |
| atr_21 | numeric | YES |
| awesome | numeric | YES |
| bb_20_upper | numeric | YES |
| bb_20_middle | numeric | YES |
| bb_20_lower | numeric | YES |
| bb_20_bandwidth | numeric | YES |
| bb_25_upper | numeric | YES |
| bb_25_middle | numeric | YES |
| bb_25_lower | numeric | YES |
| bb_25_bandwidth | numeric | YES |
| bop_14 | numeric | YES |
| cci_20 | numeric | YES |
| cmf_20 | numeric | YES |
| cvd_50 | numeric | YES |
| cvd_100 | numeric | YES |
| donchian_upper | numeric | YES |
| donchian_lower | numeric | YES |
| donchian_middle | numeric | YES |
| ema_9 | numeric | YES |
| ema_12 | numeric | YES |
| ema_21 | numeric | YES |
| ema_26 | numeric | YES |
| ema_50 | numeric | YES |
| eom_14 | numeric | YES |
| force_13 | numeric | YES |
| hma_9 | numeric | YES |
| hma_21 | numeric | YES |
| ichi_tenkan | numeric | YES |
| ichi_kijun | numeric | YES |
| ichi_senkou_a | numeric | YES |
| ichi_senkou_b | numeric | YES |
| ichi_chikou | numeric | YES |
| ichi_fast_tenkan | numeric | YES |
| ichi_fast_kijun | numeric | YES |
| keltner_upper | numeric | YES |
| keltner_middle | numeric | YES |
| keltner_lower | numeric | YES |
| linreg_14_slope | numeric | YES |
| linreg_14_intercept | numeric | YES |
| linreg_14_r2 | numeric | YES |
| linreg_14_forecast | numeric | YES |
| linreg_20_slope | numeric | YES |
| linreg_20_r2 | numeric | YES |
| macd_line | numeric | YES |
| macd_signal | numeric | YES |
| macd_histogram | numeric | YES |
| macd_fast_line | numeric | YES |
| macd_fast_signal | numeric | YES |
| macd_fast_histogram | numeric | YES |
| mfi_14 | numeric | YES |
| momentum_10 | numeric | YES |
| obv_50 | numeric | YES |
| psar_value | numeric | YES |
| psar_trend | numeric | YES |
| pivot | numeric | YES |
| pivot_r1 | numeric | YES |
| pivot_s1 | numeric | YES |
| pivot_r2 | numeric | YES |
| pivot_s2 | numeric | YES |
| pvt_50 | numeric | YES |
| roc_9 | numeric | YES |
| roc_12 | numeric | YES |
| rsi_7 | numeric | YES |
| rsi_14 | numeric | YES |
| rsi_21 | numeric | YES |
| rvi_10 | numeric | YES |
| sma_9 | numeric | YES |
| sma_20 | numeric | YES |
| sma_50 | numeric | YES |
| stochrsi_k | numeric | YES |
| stochrsi_d | numeric | YES |
| stoch_fast_k | numeric | YES |
| stoch_fast_d | numeric | YES |
| stoch_k | numeric | YES |
| stoch_d | numeric | YES |
| supertrend_fast_value | numeric | YES |
| supertrend_fast_direction | numeric | YES |
| supertrend_value | numeric | YES |
| supertrend_direction | numeric | YES |
| ulcer_14 | numeric | YES |
| ultimate_osc | numeric | YES |
| vortex_plus | numeric | YES |
| vortex_minus | numeric | YES |
| vwap_50 | numeric | YES |
| vwap_96 | numeric | YES |
| vwma_9 | numeric | YES |
| vwma_20 | numeric | YES |
| williams_14 | numeric | YES |
| wma_9 | numeric | YES |
| wma_21 | numeric | YES |

```sql
SELECT o.pair,
    o.bucket_time,
    o.open,
    o.high,
    o.low,
    o.close,
    o.volume,
    o.buy_volume,
    o.sell_volume,
    o.trade_count,
    max(iv.v1) FILTER (WHERE iv.config_id = 'adl_50_15m'::text) AS adl_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'adx_14_15m'::text) AS adx_14,
    max(iv.v2) FILTER (WHERE iv.config_id = 'adx_14_15m'::text) AS adx_14_plus_di,
    max(iv.v3) FILTER (WHERE iv.config_id = 'adx_14_15m'::text) AS adx_14_minus_di,
    max(iv.v1) FILTER (WHERE iv.config_id = 'adx_20_15m'::text) AS adx_20,
    max(iv.v2) FILTER (WHERE iv.config_id = 'adx_20_15m'::text) AS adx_20_plus_di,
    max(iv.v3) FILTER (WHERE iv.config_id = 'adx_20_15m'::text) AS adx_20_minus_di,
    max(iv.v1) FILTER (WHERE iv.config_id = 'aroon_14_15m'::text) AS aroon_14_up,
    max(iv.v2) FILTER (WHERE iv.config_id = 'aroon_14_15m'::text) AS aroon_14_down,
    max(iv.v3) FILTER (WHERE iv.config_id = 'aroon_14_15m'::text) AS aroon_14_osc,
    max(iv.v1) FILTER (WHERE iv.config_id = 'aroon_25_15m'::text) AS aroon_25_up,
    max(iv.v2) FILTER (WHERE iv.config_id = 'aroon_25_15m'::text) AS aroon_25_down,
    max(iv.v3) FILTER (WHERE iv.config_id = 'aroon_25_15m'::text) AS aroon_25_osc,
    max(iv.v1) FILTER (WHERE iv.config_id = 'atr_14_15m'::text) AS atr_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'atr_21_15m'::text) AS atr_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'awesome_5_34_15m'::text) AS awesome,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bollinger_20_2_15m'::text) AS bb_20_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'bollinger_20_2_15m'::text) AS bb_20_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'bollinger_20_2_15m'::text) AS bb_20_lower,
    max(iv.v4) FILTER (WHERE iv.config_id = 'bollinger_20_2_15m'::text) AS bb_20_bandwidth,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bollinger_20_2.5_15m'::text) AS bb_25_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'bollinger_20_2.5_15m'::text) AS bb_25_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'bollinger_20_2.5_15m'::text) AS bb_25_lower,
    max(iv.v4) FILTER (WHERE iv.config_id = 'bollinger_20_2.5_15m'::text) AS bb_25_bandwidth,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bop_14_15m'::text) AS bop_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cci_20_15m'::text) AS cci_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cmf_20_15m'::text) AS cmf_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cvd_50_15m'::text) AS cvd_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cvd_100_15m'::text) AS cvd_100,
    max(iv.v1) FILTER (WHERE iv.config_id = 'donchian_20_15m'::text) AS donchian_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'donchian_20_15m'::text) AS donchian_lower,
    max(iv.v3) FILTER (WHERE iv.config_id = 'donchian_20_15m'::text) AS donchian_middle,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_9_15m'::text) AS ema_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_12_15m'::text) AS ema_12,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_21_15m'::text) AS ema_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_26_15m'::text) AS ema_26,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_50_15m'::text) AS ema_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'eom_14_15m'::text) AS eom_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'force_13_15m'::text) AS force_13,
    max(iv.v1) FILTER (WHERE iv.config_id = 'hma_9_15m'::text) AS hma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'hma_21_15m'::text) AS hma_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_15m'::text) AS ichi_tenkan,
    max(iv.v2) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_15m'::text) AS ichi_kijun,
    max(iv.v3) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_15m'::text) AS ichi_senkou_a,
    max(iv.v4) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_15m'::text) AS ichi_senkou_b,
    max(iv.v5) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_15m'::text) AS ichi_chikou,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ichimoku_7_22_44_15m'::text) AS ichi_fast_tenkan,
    max(iv.v2) FILTER (WHERE iv.config_id = 'ichimoku_7_22_44_15m'::text) AS ichi_fast_kijun,
    max(iv.v1) FILTER (WHERE iv.config_id = 'keltner_20_10_2_15m'::text) AS keltner_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'keltner_20_10_2_15m'::text) AS keltner_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'keltner_20_10_2_15m'::text) AS keltner_lower,
    max(iv.v1) FILTER (WHERE iv.config_id = 'linreg_14_15m'::text) / NULLIF(o.open, 0::numeric) * 100::numeric AS linreg_14_slope,
    max(iv.v2) FILTER (WHERE iv.config_id = 'linreg_14_15m'::text) AS linreg_14_intercept,
    max(iv.v3) FILTER (WHERE iv.config_id = 'linreg_14_15m'::text) AS linreg_14_r2,
    max(iv.v4) FILTER (WHERE iv.config_id = 'linreg_14_15m'::text) AS linreg_14_forecast,
    max(iv.v1) FILTER (WHERE iv.config_id = 'linreg_20_15m'::text) / NULLIF(o.open, 0::numeric) * 100::numeric AS linreg_20_slope,
    max(iv.v3) FILTER (WHERE iv.config_id = 'linreg_20_15m'::text) AS linreg_20_r2,
    max(iv.v1) FILTER (WHERE iv.config_id = 'macd_12_26_9_15m'::text) AS macd_line,
    max(iv.v2) FILTER (WHERE iv.config_id = 'macd_12_26_9_15m'::text) AS macd_signal,
    max(iv.v3) FILTER (WHERE iv.config_id = 'macd_12_26_9_15m'::text) AS macd_histogram,
    max(iv.v1) FILTER (WHERE iv.config_id = 'macd_8_17_9_15m'::text) AS macd_fast_line,
    max(iv.v2) FILTER (WHERE iv.config_id = 'macd_8_17_9_15m'::text) AS macd_fast_signal,
    max(iv.v3) FILTER (WHERE iv.config_id = 'macd_8_17_9_15m'::text) AS macd_fast_histogram,
    max(iv.v1) FILTER (WHERE iv.config_id = 'mfi_14_15m'::text) AS mfi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'momentum_10_15m'::text) AS momentum_10,
    max(iv.v1) FILTER (WHERE iv.config_id = 'obv_50_15m'::text) AS obv_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'psar_02_02_20_15m'::text) AS psar_value,
    max(iv.v2) FILTER (WHERE iv.config_id = 'psar_02_02_20_15m'::text) AS psar_trend,
    max(iv.v1) FILTER (WHERE iv.config_id = 'pivot_standard_15m'::text) AS pivot,
    max(iv.v2) FILTER (WHERE iv.config_id = 'pivot_standard_15m'::text) AS pivot_r1,
    max(iv.v3) FILTER (WHERE iv.config_id = 'pivot_standard_15m'::text) AS pivot_s1,
    max(iv.v4) FILTER (WHERE iv.config_id = 'pivot_standard_15m'::text) AS pivot_r2,
    max(iv.v5) FILTER (WHERE iv.config_id = 'pivot_standard_15m'::text) AS pivot_s2,
    max(iv.v1) FILTER (WHERE iv.config_id = 'pvt_50_15m'::text) AS pvt_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'roc_9_15m'::text) AS roc_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'roc_12_15m'::text) AS roc_12,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_7_15m'::text) AS rsi_7,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_14_15m'::text) AS rsi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_21_15m'::text) AS rsi_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rvi_10_15m'::text) AS rvi_10,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_9_15m'::text) AS sma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_20_15m'::text) AS sma_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_50_15m'::text) AS sma_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stochrsi_14_14_3_3_15m'::text) AS stochrsi_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stochrsi_14_14_3_3_15m'::text) AS stochrsi_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stoch_5_3_3_15m'::text) AS stoch_fast_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stoch_5_3_3_15m'::text) AS stoch_fast_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stoch_14_3_3_15m'::text) AS stoch_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stoch_14_3_3_15m'::text) AS stoch_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'supertrend_7_2_15m'::text) AS supertrend_fast_value,
    max(iv.v2) FILTER (WHERE iv.config_id = 'supertrend_7_2_15m'::text) AS supertrend_fast_direction,
    max(iv.v1) FILTER (WHERE iv.config_id = 'supertrend_10_3_15m'::text) AS supertrend_value,
    max(iv.v2) FILTER (WHERE iv.config_id = 'supertrend_10_3_15m'::text) AS supertrend_direction,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ulcer_14_15m'::text) AS ulcer_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ultimate_7_14_28_15m'::text) AS ultimate_osc,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vortex_14_15m'::text) AS vortex_plus,
    max(iv.v2) FILTER (WHERE iv.config_id = 'vortex_14_15m'::text) AS vortex_minus,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwap_50_15m'::text) AS vwap_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwap_96_15m'::text) AS vwap_96,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwma_9_15m'::text) AS vwma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwma_20_15m'::text) AS vwma_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'williams_14_15m'::text) AS williams_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'wma_9_15m'::text) AS wma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'wma_21_15m'::text) AS wma_21
   FROM indicators.ohlcv_15m o
     LEFT JOIN indicators.indicator_values iv ON o.pair = iv.pair AND o.bucket_time = iv.bucket_time
  GROUP BY o.pair, o.bucket_time, o.open, o.high, o.low, o.close, o.volume, o.buy_volume, o.sell_volume, o.trade_count;
```

### indicators.v_model_1h

| column | data_type | nullable |
|---|---|---|
| pair | text | YES |
| bucket_time | timestamp with time zone | YES |
| open | numeric | YES |
| high | numeric | YES |
| low | numeric | YES |
| close | numeric | YES |
| volume | numeric | YES |
| buy_volume | numeric | YES |
| sell_volume | numeric | YES |
| trade_count | integer | YES |
| adl_50 | numeric | YES |
| adx_14 | numeric | YES |
| adx_14_plus_di | numeric | YES |
| adx_14_minus_di | numeric | YES |
| aroon_25_up | numeric | YES |
| aroon_25_down | numeric | YES |
| aroon_25_osc | numeric | YES |
| atr_14 | numeric | YES |
| awesome | numeric | YES |
| bb_20_upper | numeric | YES |
| bb_20_middle | numeric | YES |
| bb_20_lower | numeric | YES |
| bb_20_bandwidth | numeric | YES |
| bop_14 | numeric | YES |
| cci_20 | numeric | YES |
| cmf_20 | numeric | YES |
| cvd_50 | numeric | YES |
| donchian_upper | numeric | YES |
| donchian_lower | numeric | YES |
| donchian_middle | numeric | YES |
| ema_9 | numeric | YES |
| ema_21 | numeric | YES |
| ema_50 | numeric | YES |
| ema_200 | numeric | YES |
| eom_14 | numeric | YES |
| hma_9 | numeric | YES |
| ichi_tenkan | numeric | YES |
| ichi_kijun | numeric | YES |
| ichi_senkou_a | numeric | YES |
| ichi_senkou_b | numeric | YES |
| ichi_chikou | numeric | YES |
| keltner_upper | numeric | YES |
| keltner_middle | numeric | YES |
| keltner_lower | numeric | YES |
| linreg_14_slope | numeric | YES |
| linreg_14_r2 | numeric | YES |
| linreg_14_forecast | numeric | YES |
| macd_line | numeric | YES |
| macd_signal | numeric | YES |
| macd_histogram | numeric | YES |
| mfi_14 | numeric | YES |
| momentum_10 | numeric | YES |
| obv_50 | numeric | YES |
| psar_value | numeric | YES |
| psar_trend | numeric | YES |
| pivot | numeric | YES |
| pivot_r1 | numeric | YES |
| pivot_s1 | numeric | YES |
| pvt_50 | numeric | YES |
| roc_12 | numeric | YES |
| rsi_14 | numeric | YES |
| rsi_21 | numeric | YES |
| rvi_10 | numeric | YES |
| sma_9 | numeric | YES |
| sma_20 | numeric | YES |
| sma_50 | numeric | YES |
| sma_200 | numeric | YES |
| stochrsi_k | numeric | YES |
| stochrsi_d | numeric | YES |
| stoch_k | numeric | YES |
| stoch_d | numeric | YES |
| supertrend_value | numeric | YES |
| supertrend_direction | numeric | YES |
| ulcer_14 | numeric | YES |
| ultimate_osc | numeric | YES |
| vortex_plus | numeric | YES |
| vortex_minus | numeric | YES |
| vwap_24 | numeric | YES |
| vwma_9 | numeric | YES |
| williams_14 | numeric | YES |
| wma_9 | numeric | YES |

```sql
SELECT o.pair,
    o.bucket_time,
    o.open,
    o.high,
    o.low,
    o.close,
    o.volume,
    o.buy_volume,
    o.sell_volume,
    o.trade_count,
    max(iv.v1) FILTER (WHERE iv.config_id = 'adl_50_1h'::text) AS adl_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'adx_14_1h'::text) AS adx_14,
    max(iv.v2) FILTER (WHERE iv.config_id = 'adx_14_1h'::text) AS adx_14_plus_di,
    max(iv.v3) FILTER (WHERE iv.config_id = 'adx_14_1h'::text) AS adx_14_minus_di,
    max(iv.v1) FILTER (WHERE iv.config_id = 'aroon_25_1h'::text) AS aroon_25_up,
    max(iv.v2) FILTER (WHERE iv.config_id = 'aroon_25_1h'::text) AS aroon_25_down,
    max(iv.v3) FILTER (WHERE iv.config_id = 'aroon_25_1h'::text) AS aroon_25_osc,
    max(iv.v1) FILTER (WHERE iv.config_id = 'atr_14_1h'::text) AS atr_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'awesome_5_34_1h'::text) AS awesome,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bollinger_20_2_1h'::text) AS bb_20_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'bollinger_20_2_1h'::text) AS bb_20_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'bollinger_20_2_1h'::text) AS bb_20_lower,
    max(iv.v4) FILTER (WHERE iv.config_id = 'bollinger_20_2_1h'::text) AS bb_20_bandwidth,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bop_14_1h'::text) AS bop_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cci_20_1h'::text) AS cci_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cmf_20_1h'::text) AS cmf_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cvd_50_1h'::text) AS cvd_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'donchian_20_1h'::text) AS donchian_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'donchian_20_1h'::text) AS donchian_lower,
    max(iv.v3) FILTER (WHERE iv.config_id = 'donchian_20_1h'::text) AS donchian_middle,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_9_1h'::text) AS ema_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_21_1h'::text) AS ema_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_50_1h'::text) AS ema_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_200_1h'::text) AS ema_200,
    max(iv.v1) FILTER (WHERE iv.config_id = 'eom_14_1h'::text) AS eom_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'hma_9_1h'::text) AS hma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_1h'::text) AS ichi_tenkan,
    max(iv.v2) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_1h'::text) AS ichi_kijun,
    max(iv.v3) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_1h'::text) AS ichi_senkou_a,
    max(iv.v4) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_1h'::text) AS ichi_senkou_b,
    max(iv.v5) FILTER (WHERE iv.config_id = 'ichimoku_9_26_52_1h'::text) AS ichi_chikou,
    max(iv.v1) FILTER (WHERE iv.config_id = 'keltner_20_10_2_1h'::text) AS keltner_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'keltner_20_10_2_1h'::text) AS keltner_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'keltner_20_10_2_1h'::text) AS keltner_lower,
    max(iv.v1) FILTER (WHERE iv.config_id = 'linreg_14_1h'::text) / NULLIF(o.open, 0::numeric) * 100::numeric AS linreg_14_slope,
    max(iv.v3) FILTER (WHERE iv.config_id = 'linreg_14_1h'::text) AS linreg_14_r2,
    max(iv.v4) FILTER (WHERE iv.config_id = 'linreg_14_1h'::text) AS linreg_14_forecast,
    max(iv.v1) FILTER (WHERE iv.config_id = 'macd_12_26_9_1h'::text) AS macd_line,
    max(iv.v2) FILTER (WHERE iv.config_id = 'macd_12_26_9_1h'::text) AS macd_signal,
    max(iv.v3) FILTER (WHERE iv.config_id = 'macd_12_26_9_1h'::text) AS macd_histogram,
    max(iv.v1) FILTER (WHERE iv.config_id = 'mfi_14_1h'::text) AS mfi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'momentum_10_1h'::text) AS momentum_10,
    max(iv.v1) FILTER (WHERE iv.config_id = 'obv_50_1h'::text) AS obv_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'psar_02_02_20_1h'::text) AS psar_value,
    max(iv.v2) FILTER (WHERE iv.config_id = 'psar_02_02_20_1h'::text) AS psar_trend,
    max(iv.v1) FILTER (WHERE iv.config_id = 'pivot_standard_1h'::text) AS pivot,
    max(iv.v2) FILTER (WHERE iv.config_id = 'pivot_standard_1h'::text) AS pivot_r1,
    max(iv.v3) FILTER (WHERE iv.config_id = 'pivot_standard_1h'::text) AS pivot_s1,
    max(iv.v1) FILTER (WHERE iv.config_id = 'pvt_50_1h'::text) AS pvt_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'roc_12_1h'::text) AS roc_12,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_14_1h'::text) AS rsi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_21_1h'::text) AS rsi_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rvi_10_1h'::text) AS rvi_10,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_9_1h'::text) AS sma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_20_1h'::text) AS sma_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_50_1h'::text) AS sma_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_200_1h'::text) AS sma_200,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stochrsi_14_14_3_3_1h'::text) AS stochrsi_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stochrsi_14_14_3_3_1h'::text) AS stochrsi_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stoch_14_3_3_1h'::text) AS stoch_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stoch_14_3_3_1h'::text) AS stoch_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'supertrend_10_3_1h'::text) AS supertrend_value,
    max(iv.v2) FILTER (WHERE iv.config_id = 'supertrend_10_3_1h'::text) AS supertrend_direction,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ulcer_14_1h'::text) AS ulcer_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ultimate_7_14_28_1h'::text) AS ultimate_osc,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vortex_14_1h'::text) AS vortex_plus,
    max(iv.v2) FILTER (WHERE iv.config_id = 'vortex_14_1h'::text) AS vortex_minus,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwap_24_1h'::text) AS vwap_24,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwma_9_1h'::text) AS vwma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'williams_14_1h'::text) AS williams_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'wma_9_1h'::text) AS wma_9
   FROM indicators.ohlcv_1h o
     LEFT JOIN indicators.indicator_values iv ON o.pair = iv.pair AND o.bucket_time = iv.bucket_time
  GROUP BY o.pair, o.bucket_time, o.open, o.high, o.low, o.close, o.volume, o.buy_volume, o.sell_volume, o.trade_count;
```

### indicators.v_model_1m

| column | data_type | nullable |
|---|---|---|
| pair | text | YES |
| bucket_time | timestamp with time zone | YES |
| open | numeric | YES |
| high | numeric | YES |
| low | numeric | YES |
| close | numeric | YES |
| volume | numeric | YES |
| buy_volume | numeric | YES |
| sell_volume | numeric | YES |
| trade_count | integer | YES |
| atr_14 | numeric | YES |
| cvd_20 | numeric | YES |
| ema_9 | numeric | YES |
| ema_12 | numeric | YES |
| ema_21 | numeric | YES |
| ema_26 | numeric | YES |
| rsi_7 | numeric | YES |
| rsi_14 | numeric | YES |
| sma_9 | numeric | YES |
| sma_20 | numeric | YES |
| macd_line | numeric | YES |
| macd_signal | numeric | YES |
| macd_histogram | numeric | YES |

```sql
SELECT o.pair,
    o.bucket_time,
    o.open,
    o.high,
    o.low,
    o.close,
    o.volume,
    o.buy_volume,
    o.sell_volume,
    o.trade_count,
    max(iv.v1) FILTER (WHERE iv.config_id = 'atr_14_1m'::text) AS atr_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cvd_20_1m'::text) AS cvd_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_9_1m'::text) AS ema_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_12_1m'::text) AS ema_12,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_21_1m'::text) AS ema_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_26_1m'::text) AS ema_26,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_7_1m'::text) AS rsi_7,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_14_1m'::text) AS rsi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_9_1m'::text) AS sma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_20_1m'::text) AS sma_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'macd_12_26_9_1m'::text) AS macd_line,
    max(iv.v2) FILTER (WHERE iv.config_id = 'macd_12_26_9_1m'::text) AS macd_signal,
    max(iv.v3) FILTER (WHERE iv.config_id = 'macd_12_26_9_1m'::text) AS macd_histogram
   FROM indicators.ohlcv_1m o
     LEFT JOIN indicators.indicator_values iv ON o.pair = iv.pair AND o.bucket_time = iv.bucket_time
  GROUP BY o.pair, o.bucket_time, o.open, o.high, o.low, o.close, o.volume, o.buy_volume, o.sell_volume, o.trade_count;
```

### indicators.v_model_5m

| column | data_type | nullable |
|---|---|---|
| pair | text | YES |
| bucket_time | timestamp with time zone | YES |
| open | numeric | YES |
| high | numeric | YES |
| low | numeric | YES |
| close | numeric | YES |
| volume | numeric | YES |
| buy_volume | numeric | YES |
| sell_volume | numeric | YES |
| trade_count | integer | YES |
| adx_14 | numeric | YES |
| adx_14_plus_di | numeric | YES |
| adx_14_minus_di | numeric | YES |
| atr_7 | numeric | YES |
| atr_14 | numeric | YES |
| awesome | numeric | YES |
| bb_20_upper | numeric | YES |
| bb_20_middle | numeric | YES |
| bb_20_lower | numeric | YES |
| bb_20_bandwidth | numeric | YES |
| bb_10_upper | numeric | YES |
| bb_10_middle | numeric | YES |
| bb_10_lower | numeric | YES |
| bop_14 | numeric | YES |
| cci_20 | numeric | YES |
| cmf_10 | numeric | YES |
| cmf_20 | numeric | YES |
| cvd_50 | numeric | YES |
| donchian_upper | numeric | YES |
| donchian_lower | numeric | YES |
| donchian_middle | numeric | YES |
| ema_9 | numeric | YES |
| ema_12 | numeric | YES |
| ema_21 | numeric | YES |
| ema_26 | numeric | YES |
| force_2 | numeric | YES |
| force_13 | numeric | YES |
| linreg_slope | numeric | YES |
| linreg_intercept | numeric | YES |
| linreg_r2 | numeric | YES |
| linreg_forecast | numeric | YES |
| macd_line | numeric | YES |
| macd_signal | numeric | YES |
| macd_histogram | numeric | YES |
| macd_fast_line | numeric | YES |
| macd_fast_signal | numeric | YES |
| macd_fast_histogram | numeric | YES |
| mfi_14 | numeric | YES |
| momentum_10 | numeric | YES |
| obv_50 | numeric | YES |
| roc_9 | numeric | YES |
| rsi_7 | numeric | YES |
| rsi_14 | numeric | YES |
| sma_9 | numeric | YES |
| sma_20 | numeric | YES |
| stoch_fast_k | numeric | YES |
| stoch_fast_d | numeric | YES |
| stoch_k | numeric | YES |
| stoch_d | numeric | YES |
| supertrend_value | numeric | YES |
| supertrend_direction | numeric | YES |
| vwap_20 | numeric | YES |
| williams_14 | numeric | YES |

```sql
SELECT o.pair,
    o.bucket_time,
    o.open,
    o.high,
    o.low,
    o.close,
    o.volume,
    o.buy_volume,
    o.sell_volume,
    o.trade_count,
    max(iv.v1) FILTER (WHERE iv.config_id = 'adx_14_5m'::text) AS adx_14,
    max(iv.v2) FILTER (WHERE iv.config_id = 'adx_14_5m'::text) AS adx_14_plus_di,
    max(iv.v3) FILTER (WHERE iv.config_id = 'adx_14_5m'::text) AS adx_14_minus_di,
    max(iv.v1) FILTER (WHERE iv.config_id = 'atr_7_5m'::text) AS atr_7,
    max(iv.v1) FILTER (WHERE iv.config_id = 'atr_14_5m'::text) AS atr_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'awesome_5_34_5m'::text) AS awesome,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bollinger_20_2_5m'::text) AS bb_20_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'bollinger_20_2_5m'::text) AS bb_20_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'bollinger_20_2_5m'::text) AS bb_20_lower,
    max(iv.v4) FILTER (WHERE iv.config_id = 'bollinger_20_2_5m'::text) AS bb_20_bandwidth,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bollinger_10_1.5_5m'::text) AS bb_10_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'bollinger_10_1.5_5m'::text) AS bb_10_middle,
    max(iv.v3) FILTER (WHERE iv.config_id = 'bollinger_10_1.5_5m'::text) AS bb_10_lower,
    max(iv.v1) FILTER (WHERE iv.config_id = 'bop_14_5m'::text) AS bop_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cci_20_5m'::text) AS cci_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cmf_10_5m'::text) AS cmf_10,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cmf_20_5m'::text) AS cmf_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'cvd_50_5m'::text) AS cvd_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'donchian_20_5m'::text) AS donchian_upper,
    max(iv.v2) FILTER (WHERE iv.config_id = 'donchian_20_5m'::text) AS donchian_lower,
    max(iv.v3) FILTER (WHERE iv.config_id = 'donchian_20_5m'::text) AS donchian_middle,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_9_5m'::text) AS ema_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_12_5m'::text) AS ema_12,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_21_5m'::text) AS ema_21,
    max(iv.v1) FILTER (WHERE iv.config_id = 'ema_26_5m'::text) AS ema_26,
    max(iv.v1) FILTER (WHERE iv.config_id = 'force_2_5m'::text) AS force_2,
    max(iv.v1) FILTER (WHERE iv.config_id = 'force_13_5m'::text) AS force_13,
    max(iv.v1) FILTER (WHERE iv.config_id = 'linreg_14_5m'::text) / NULLIF(o.open, 0::numeric) * 100::numeric AS linreg_slope,
    max(iv.v2) FILTER (WHERE iv.config_id = 'linreg_14_5m'::text) AS linreg_intercept,
    max(iv.v3) FILTER (WHERE iv.config_id = 'linreg_14_5m'::text) AS linreg_r2,
    max(iv.v4) FILTER (WHERE iv.config_id = 'linreg_14_5m'::text) AS linreg_forecast,
    max(iv.v1) FILTER (WHERE iv.config_id = 'macd_12_26_9_5m'::text) AS macd_line,
    max(iv.v2) FILTER (WHERE iv.config_id = 'macd_12_26_9_5m'::text) AS macd_signal,
    max(iv.v3) FILTER (WHERE iv.config_id = 'macd_12_26_9_5m'::text) AS macd_histogram,
    max(iv.v1) FILTER (WHERE iv.config_id = 'macd_8_17_9_5m'::text) AS macd_fast_line,
    max(iv.v2) FILTER (WHERE iv.config_id = 'macd_8_17_9_5m'::text) AS macd_fast_signal,
    max(iv.v3) FILTER (WHERE iv.config_id = 'macd_8_17_9_5m'::text) AS macd_fast_histogram,
    max(iv.v1) FILTER (WHERE iv.config_id = 'mfi_14_5m'::text) AS mfi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'momentum_10_5m'::text) AS momentum_10,
    max(iv.v1) FILTER (WHERE iv.config_id = 'obv_50_5m'::text) AS obv_50,
    max(iv.v1) FILTER (WHERE iv.config_id = 'roc_9_5m'::text) AS roc_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_7_5m'::text) AS rsi_7,
    max(iv.v1) FILTER (WHERE iv.config_id = 'rsi_14_5m'::text) AS rsi_14,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_9_5m'::text) AS sma_9,
    max(iv.v1) FILTER (WHERE iv.config_id = 'sma_20_5m'::text) AS sma_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stoch_5_3_3_5m'::text) AS stoch_fast_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stoch_5_3_3_5m'::text) AS stoch_fast_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'stoch_14_3_3_5m'::text) AS stoch_k,
    max(iv.v2) FILTER (WHERE iv.config_id = 'stoch_14_3_3_5m'::text) AS stoch_d,
    max(iv.v1) FILTER (WHERE iv.config_id = 'supertrend_10_3_5m'::text) AS supertrend_value,
    max(iv.v2) FILTER (WHERE iv.config_id = 'supertrend_10_3_5m'::text) AS supertrend_direction,
    max(iv.v1) FILTER (WHERE iv.config_id = 'vwap_20_5m'::text) AS vwap_20,
    max(iv.v1) FILTER (WHERE iv.config_id = 'williams_14_5m'::text) AS williams_14
   FROM indicators.ohlcv_5m o
     LEFT JOIN indicators.indicator_values iv ON o.pair = iv.pair AND o.bucket_time = iv.bucket_time
  GROUP BY o.pair, o.bucket_time, o.open, o.high, o.low, o.close, o.volume, o.buy_volume, o.sell_volume, o.trade_count;
```

### indicators.v_null_summary

| column | data_type | nullable |
|---|---|---|
| config_id | text | YES |
| null_count | bigint | YES |
| first_null | timestamp with time zone | YES |
| last_null | timestamp with time zone | YES |

```sql
SELECT config_id,
    count(*) AS null_count,
    min(bucket_time) AS first_null,
    max(bucket_time) AS last_null
   FROM indicators.computation_log
  WHERE status = 'null_result'::text AND created_at >= (now() - '24:00:00'::interval)
  GROUP BY config_id
  ORDER BY (count(*)) DESC;
```

### indicators.v_recent_errors

| column | data_type | nullable |
|---|---|---|
| created_at | timestamp with time zone | YES |
| pair | text | YES |
| bucket_time | timestamp with time zone | YES |
| config_id | text | YES |
| error_message | text | YES |

```sql
SELECT created_at,
    pair,
    bucket_time,
    config_id,
    error_message
   FROM indicators.computation_log
  WHERE status = 'error'::text AND created_at >= (now() - '24:00:00'::interval)
  ORDER BY created_at DESC;
```

### indicators.v_slow_computations

| column | data_type | nullable |
|---|---|---|
| config_id | text | YES |
| avg_ms | numeric | YES |
| max_ms | integer | YES |
| sample_count | bigint | YES |

```sql
SELECT config_id,
    avg(execution_ms) AS avg_ms,
    max(execution_ms) AS max_ms,
    count(*) AS sample_count
   FROM indicators.computation_log
  WHERE status = 'success'::text AND execution_ms IS NOT NULL AND created_at >= (now() - '24:00:00'::interval)
  GROUP BY config_id
 HAVING avg(execution_ms) > 20::numeric
  ORDER BY (avg(execution_ms)) DESC;
```

## Functions
| name | args | returns | volatility | security_definer | language |
|---|---|---|---|---|---|
| fn_backfill_ohlcv | (p_lookback interval) | TABLE(timeframe text, rows_inserted bigint) | VOLATILE | NO | plpgsql |
| fn_backfill_oi_features | (p_from timestamp with time zone, p_to timestamp with time zone) | integer | VOLATILE | YES | plpgsql |
| fn_backfill_order_book_indicators | (p_lookback interval) | integer | VOLATILE | NO | plpgsql |
| fn_cascade_timeframes | (p_pair text, p_closed_1m_bucket timestamp with time zone) | void | VOLATILE | NO | plpgsql |
| fn_compute_adl | (p_pair text, p_timeframe text, p_lookback integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_adx | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | TABLE(adx numeric, plus_di numeric, minus_di numeric) | STABLE | NO | plpgsql |
| fn_compute_all_indicators | (p_pair text, p_bucket_time timestamp with time zone, p_timeframe text, p_category text) | TABLE(computed_count integer, error_count integer, errors jsonb) | VOLATILE | NO | plpgsql |
| fn_compute_all_indicators | (p_pair text, p_bucket_time timestamp with time zone, p_timeframe text, p_category text, p_triggered_by text) | TABLE(computed_count integer, error_count integer, null_count integer, errors jsonb) | VOLATILE | NO | plpgsql |
| fn_compute_aroon | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | TABLE(aroon_up numeric, aroon_down numeric, aroon_osc numeric) | STABLE | NO | plpgsql |
| fn_compute_atr | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_awesome_oscillator | (p_pair text, p_timeframe text, p_fast_period integer, p_slow_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_bollinger | (p_pair text, p_timeframe text, p_period integer, p_std_dev numeric, p_bucket_time timestamp with time zone) | TABLE(upper_band numeric, middle_band numeric, lower_band numeric, bandwidth numeric) | STABLE | NO | plpgsql |
| fn_compute_bop | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_cci | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_cmf | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_cvd | (p_pair text, p_timeframe text, p_lookback integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_donchian | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | TABLE(upper_band numeric, lower_band numeric, middle_band numeric) | STABLE | NO | plpgsql |
| fn_compute_ema | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_eom | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_force_index | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_hma | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_ichimoku | (p_pair text, p_timeframe text, p_tenkan integer, p_kijun integer, p_senkou_b integer, p_bucket_time timestamp with time zone) | TABLE(tenkan numeric, kijun numeric, senkou_a numeric, senkou_b numeric, chikou numeric) | STABLE | NO | plpgsql |
| fn_compute_keltner | (p_pair text, p_timeframe text, p_ema_period integer, p_atr_period integer, p_multiplier numeric, p_bucket_time timestamp with time zone) | TABLE(upper_band numeric, middle_band numeric, lower_band numeric) | STABLE | NO | plpgsql |
| fn_compute_linear_regression | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | TABLE(slope numeric, intercept numeric, r_squared numeric, forecast numeric) | STABLE | NO | plpgsql |
| fn_compute_macd | (p_pair text, p_timeframe text, p_fast_period integer, p_slow_period integer, p_signal_period integer, p_bucket_time timestamp with time zone) | TABLE(macd_line numeric, signal_line numeric, histogram numeric) | STABLE | NO | plpgsql |
| fn_compute_mfi | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_momentum | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_obv | (p_pair text, p_timeframe text, p_lookback integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_oi_features_for_bucket | (p_bucket_time timestamp with time zone) | TABLE(out_symbol text, out_bucket_time timestamp with time zone, out_action text) | VOLATILE | YES | plpgsql |
| fn_compute_oi_features_recent | (p_lookback interval) | integer | VOLATILE | YES | plpgsql |
| fn_compute_order_book_indicators | (p_pair text, p_captured_at timestamp with time zone) | void | VOLATILE | NO | plpgsql |
| fn_compute_parabolic_sar | (p_pair text, p_timeframe text, p_af_start numeric, p_af_increment numeric, p_af_max numeric, p_bucket_time timestamp with time zone) | TABLE(sar numeric, trend integer) | STABLE | NO | plpgsql |
| fn_compute_pivot_points | (p_pair text, p_timeframe text, p_bucket_time timestamp with time zone) | TABLE(pivot numeric, r1 numeric, r2 numeric, r3 numeric, s1 numeric, s2 numeric, s3 numeric) | STABLE | NO | plpgsql |
| fn_compute_pvt | (p_pair text, p_timeframe text, p_lookback integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_roc | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_rsi | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_rvi | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_sma | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_stoch_rsi | (p_pair text, p_timeframe text, p_rsi_period integer, p_stoch_period integer, p_k_smooth integer, p_d_smooth integer, p_bucket_time timestamp with time zone) | TABLE(k numeric, d numeric) | STABLE | NO | plpgsql |
| fn_compute_stochastic | (p_pair text, p_timeframe text, p_k_period integer, p_d_period integer, p_bucket_time timestamp with time zone) | TABLE(k numeric, d numeric) | STABLE | NO | plpgsql |
| fn_compute_supertrend | (p_pair text, p_timeframe text, p_period integer, p_multiplier numeric, p_bucket_time timestamp with time zone) | TABLE(supertrend numeric, direction integer) | STABLE | NO | plpgsql |
| fn_compute_ulcer_index | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_ultimate_oscillator | (p_pair text, p_timeframe text, p_period1 integer, p_period2 integer, p_period3 integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_vortex | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | TABLE(plus_vi numeric, minus_vi numeric) | STABLE | NO | plpgsql |
| fn_compute_vwap | (p_pair text, p_timeframe text, p_lookback integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_vwma | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_williams_r | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_compute_wma | (p_pair text, p_timeframe text, p_period integer, p_bucket_time timestamp with time zone) | numeric | STABLE | NO | plpgsql |
| fn_create_indicator_partitions | (p_weeks_ahead integer) | integer | VOLATILE | NO | plpgsql |
| fn_ensure_15m_jobs | () | TABLE(out_pair text, out_bucket_time timestamp with time zone, out_action text) | VOLATILE | NO | plpgsql |
| fn_ensure_1h_jobs | () | TABLE(out_pair text, out_bucket_time timestamp with time zone, out_action text) | VOLATILE | NO | plpgsql |
| fn_health_check | () | TABLE(metric text, current_value text, health text) | VOLATILE | NO | plpgsql |
| fn_process_new_trade | () | trigger | VOLATILE | YES | plpgsql |
| fn_rollup_ohlcv | (p_pair text, p_timeframe text, p_bucket_time timestamp with time zone) | void | VOLATILE | NO | plpgsql |
| get_pending_indicator_jobs | (batch_size integer) | TABLE(id bigint, pair text, bucket_time timestamp with time zone, timeframe text) | VOLATILE | YES | plpgsql |

## Triggers Calling This Schema’s Functions
| table | trigger | function |
|---|---|---|
| raw_trades | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_01 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_02 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_03 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_04 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_05 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_06 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_07 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_08 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_09 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_10 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_11 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2026_12 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_01 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_02 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_03 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_04 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_05 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_06 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_07 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_08 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_09 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_10 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_11 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2027_12 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_01 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_02 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_03 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_04 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_05 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_06 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_07 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_08 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_09 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_10 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_11 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |
| raw_trades_2028_12 | trg_raw_trade_to_indicators | indicators.fn_process_new_trade |

## Trigger Definitions
### raw_trades :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_01 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_01 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_02 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_02 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_03 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_03 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_04 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_04 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_05 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_05 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_06 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_06 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_07 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_07 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_08 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_08 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_09 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_09 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_10 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_10 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_11 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_11 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2026_12 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2026_12 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_01 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_01 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_02 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_02 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_03 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_03 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_04 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_04 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_05 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_05 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_06 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_06 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_07 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_07 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_08 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_08 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_09 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_09 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_10 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_10 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_11 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_11 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2027_12 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2027_12 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_01 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_01 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_02 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_02 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_03 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_03 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_04 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_04 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_05 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_05 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_06 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_06 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_07 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_07 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_08 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_08 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_09 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_09 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_10 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_10 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_11 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_11 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

### raw_trades_2028_12 :: trg_raw_trade_to_indicators

- function: `indicators.fn_process_new_trade`
```sql
CREATE TRIGGER trg_raw_trade_to_indicators AFTER INSERT ON raw_trades_2028_12 FOR EACH ROW EXECUTE FUNCTION indicators.fn_process_new_trade()
```

## Column Reference (Populated Tables Only)
### indicators.computation_log

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO | nextval('indicators.computation_log_id_seq'::regclass) |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| timeframe | text | NO |  |
| config_id | text | YES |  |
| status | text | NO |  |
| error_message | text | YES |  |
| rows_affected | integer | YES | 0 |
| execution_ms | integer | YES |  |
| triggered_by | text | YES | 'manual'::text |
| created_at | timestamp with time zone | YES | now() |

### indicators.indicator_configs

| column | data_type | nullable | default |
|---|---|---|---|
| config_id | text | NO |  |
| indicator_name | text | NO |  |
| category | text | NO |  |
| timeframe | text | NO |  |
| params | jsonb | NO | '{}'::jsonb |
| output_columns | jsonb | NO | '{"v1": "value"}'::jsonb |
| description | text | YES |  |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |

### indicators.indicator_values_w2026_04

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| config_id | text | NO |  |
| v1 | numeric | YES |  |
| v2 | numeric | YES |  |
| v3 | numeric | YES |  |
| v4 | numeric | YES |  |
| v5 | numeric | YES |  |
| created_at | timestamp with time zone | NO | now() |

### indicators.indicator_values_w2026_05

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| config_id | text | NO |  |
| v1 | numeric | YES |  |
| v2 | numeric | YES |  |
| v3 | numeric | YES |  |
| v4 | numeric | YES |  |
| v5 | numeric | YES |  |
| created_at | timestamp with time zone | NO | now() |

### indicators.indicator_values_w2026_06

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| config_id | text | NO |  |
| v1 | numeric | YES |  |
| v2 | numeric | YES |  |
| v3 | numeric | YES |  |
| v4 | numeric | YES |  |
| v5 | numeric | YES |  |
| created_at | timestamp with time zone | NO | now() |

### indicators.job_queue

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO | nextval('indicators.job_queue_id_seq'::regclass) |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| timeframe | text | NO |  |
| status | text | NO | 'pending'::text |
| created_at | timestamp with time zone | NO | now() |
| started_at | timestamp with time zone | YES |  |
| completed_at | timestamp with time zone | YES |  |

### indicators.ohlcv_10m

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_12h

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_15m

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_1h

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_1m

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_2h

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_30m

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_45m

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_5m

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.ohlcv_6h

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open | numeric | NO |  |
| high | numeric | NO |  |
| low | numeric | NO |  |
| close | numeric | NO |  |
| volume | numeric | NO | 0 |
| buy_volume | numeric | NO | 0 |
| sell_volume | numeric | NO | 0 |
| trade_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

### indicators.oi_features

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| pair | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| divergence_1h | double precision | YES |  |
| divergence_4h | double precision | YES |  |
| funding_oi_pressure | double precision | YES |  |
| funding_oi_pressure_1h | double precision | YES |  |
| basis_pct | double precision | YES |  |
| oi_roc_1h | double precision | YES |  |
| oi_roc_4h | double precision | YES |  |
| oi_roc_24h | double precision | YES |  |
| oi_acceleration | double precision | YES |  |
| weak_rally_streak | integer | NO | 0 |
| weak_selloff_streak | integer | NO | 0 |
| oi_ema_8 | double precision | YES |  |
| oi_ema_24 | double precision | YES |  |
| oi_ema_dev_8 | double precision | YES |  |
| oi_ema_dev_24 | double precision | YES |  |
| price_oi_corr_16 | double precision | YES |  |
| price_oi_corr_24 | double precision | YES |  |
| oi_change_vol_pctile_24h | double precision | YES |  |
| turnover_1h | double precision | YES |  |
| turnover_4h | double precision | YES |  |
| source_time | timestamp with time zone | YES |  |
| computed_at | timestamp with time zone | NO | now() |

### indicators.open_interest

| column | data_type | nullable | default |
|---|---|---|---|
| symbol | text | NO |  |
| pair | text | NO |  |
| binance_symbol | text | NO |  |
| bucket_time | timestamp with time zone | NO |  |
| open_interest | double precision | NO |  |
| oi_change | double precision | NO |  |
| oi_change_pct | double precision | NO |  |
| close_price | double precision | NO |  |
| volume | double precision | NO |  |
| price_change_pct | double precision | NO |  |
| oi_volume_ratio | double precision | NO |  |
| oi_divergence | integer | NO |  |
| weak_rally | integer | NO |  |
| weak_selloff | integer | NO |  |
| source_time | timestamp with time zone | NO |  |
| ingested_at | timestamp with time zone | NO | now() |
| mark_price | double precision | YES |  |
| open_interest_notional | double precision | YES |  |
| funding_rate | double precision | YES |  |
| funding_rate_8h_avg | double precision | YES |  |
| funding_next_time | timestamp with time zone | YES |  |
| funding_source_time | timestamp with time zone | YES |  |

### indicators.order_book_indicators

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| pair | text | NO |  |
| captured_at | timestamp with time zone | NO |  |
| depth_ratio | numeric | YES |  |
| imbalance | numeric | YES |  |
| spread_pct | numeric | YES |  |
| mid_price | numeric | YES |  |
| bid_depth_10bps | numeric | YES |  |
| ask_depth_10bps | numeric | YES |  |
| bid_depth_25bps | numeric | YES |  |
| ask_depth_25bps | numeric | YES |  |
| bid_depth_50bps | numeric | YES |  |
| ask_depth_50bps | numeric | YES |  |
| bid_slope | numeric | YES |  |
| ask_slope | numeric | YES |  |
| slippage_buy_100 | numeric | YES |  |
| slippage_sell_100 | numeric | YES |  |
| slippage_buy_1000 | numeric | YES |  |
| slippage_sell_1000 | numeric | YES |  |
| created_at | timestamp with time zone | NO | now() |

### indicators.readme

| column | data_type | nullable | default |
|---|---|---|---|
| id | integer | NO | nextval('indicators.readme_id_seq'::regclass) |
| entry_type | text | NO |  |
| title | text | NO |  |
| content | text | NO |  |
| context | text | YES |  |
| tags | ARRAY | YES | '{}'::text[] |
| created_by | text | YES | 'claude'::text |
| created_at | timestamp with time zone | YES | now() |
| updated_at | timestamp with time zone | YES | now() |

### indicators.temp-table1

| column | data_type | nullable | default |
|---|---|---|---|
| id | bigint | NO |  |
| prediction | text | YES |  |
| confidence | double precision | YES |  |
| pair | text | YES |  |
| actual_price_change_pct | double precision | YES |  |
| outcome | text | YES |  |
| interval_start | timestamp with time zone | YES |  |
| accurate | boolean | YES |  |
| indicators_created_at | timestamp with time zone | YES |  |
| adx_14_15m | numeric | YES |  |
| adx_14_1h | numeric | YES |  |
| atr_14_15m | numeric | YES |  |
| atr_14_1h | numeric | YES |  |
| atr_14_5m | numeric | YES |  |
| ulcer_14_15m | numeric | YES |  |
| cmf_20_15m | numeric | YES |  |
| mfi_14_15m | numeric | YES |  |
| vwap_50_15m | numeric | YES |  |
| vwap_96_15m | numeric | YES |  |
| rsi_7_15m | numeric | YES |  |
| rsi_14_15m | numeric | YES |  |
| rsi_7_5m | numeric | YES |  |
| ema_9_15m | numeric | YES |  |
| ema_21_15m | numeric | YES |  |
| ema_50_15m | numeric | YES |  |
| ema_21_1h | numeric | YES |  |
| ema_50_1h | numeric | YES |  |
| cvd_50_15m | numeric | YES |  |
| bollinger_upper_15m | numeric | YES |  |
| bollinger_middle_15m | numeric | YES |  |
| bollinger_lower_15m | numeric | YES |  |
| bollinger_bandwidth_15m | numeric | YES |  |
| stochrsi_k_15m | numeric | YES |  |
| stochrsi_d_15m | numeric | YES |  |
| ichimoku_tenkan_15m | numeric | YES |  |
| ichimoku_kijun_15m | numeric | YES |  |
| ichimoku_senkou_a_15m | numeric | YES |  |
| ichimoku_senkou_b_15m | numeric | YES |  |
| ichimoku_chikou_15m | numeric | YES |  |
| supertrend_value_15m | numeric | YES |  |
| supertrend_direction_15m | numeric | YES |  |

## Synthetic Indicator Subsystem (Added 2026-02-11)

A parallel synthetic subsystem exists under `indicators`:
- `synthetic_indicator_configs`
- `synthetic_indicator_values`
- `synthetic_job_queue`
- `v_synthetic_signal_inputs`

This subsystem is intentionally isolated from the existing classic indicator pipeline and is designed for metadata-driven filter signals used by prediction logic.

See: `docs/SYNTHETIC_INDICATORS_SCHEMA.md`.
