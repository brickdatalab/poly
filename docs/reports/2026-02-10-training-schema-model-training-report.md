# Training Schema: Model-Training Report (BTC/ETH Focus)

Source review run: `/Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/runs/20260210T160002Z/REPORT.md`

## 1) What Candle Data Exists (Training Schema)

### 1m candles: `training.spot_1m`
- Grain: `(symbol, ts)`
- Columns: OHLCV (`open`, `high`, `low`, `close`, `volume`)
- Extra columns (precomputed “classic” indicators embedded in the table): moving averages (`ma_20`, `ma_50`, `ma_200`), `rsi`, `macd`, `macd_signal`, Bollinger (`bb_upper`, `bb_middle`, `bb_lower`), stochastic (`stoch_k`, `stoch_d`), `adx`, `atr`, `obv`, `vwap`, `trendline_support`, `trendline_resistance`.
- Basic integrity checks (run output): no off-grid timestamps, no negative volume, no OHLC bound violations.
- Freshness note: this table ends much earlier than the 15m/1h sets (`max_ts` around 2025-03-19 in the run).

### 15m candles: `training.spot_15m`
- Grain: `(symbol, open_time)`
- Columns: OHLCV (`open`, `high`, `low`, `close`, `volume`)
- Label/target-like columns already present: `label`, `pct_change` (+ `pct_change_zscore`)
- Extra candle-shape columns: `high_low_range`, `upper_wick_pct`, `lower_wick_pct`
- Exchange-specific microstructure columns (Binance-style): `num_trades`, `quote_volume`, `taker_buy_base_vol`, `taker_buy_quote_vol`

### 1h candles: `training.spot_1h`
- Same structure as `training.spot_15m` (OHLCV + `label`, `pct_change`, `num_trades`, taker-buy vols, wick/range features).

### Timeframes that are NOT present in training
- There are no native 2h / 6d candle tables in the `training` schema.
- If you need 2h / 6h / 12h / etc, those exist on the serving side in the `indicators` schema, not in training.

## 2) Indicator-Linked Training Data (What You Can Use as Features)

### Wide indicator tables (most direct “features per candle”)
- `training.spot_15m_indicators` (15m): 104 columns total; 102 numeric indicator features + keys.
- `training.spot_1h_indicators` (1h): same column count shape.

These tables are the closest thing to “one row per candle with a large feature vector”.

### Curated / unified feature tables
- `training.unified_15m`: 77 columns total (73 numeric features); includes a `label` distribution in the review run.
- `training.unified_1h`: 76 columns total (72 numeric features); includes a `label` distribution in the review run.
- `training.synthetic_features`: 35 columns total (31 numeric features); also includes a label distribution.

These are narrower than the wide indicator tables and (by convention) are better starting points for first-pass training because the feature set is already curated.

### RT-aligned training views (recommended when the serving contract is `indicators.*`)
The training schema includes views that are explicitly designed to align with realtime serving features derived from `indicators.v_model_*`, for example:

- `training.v_rt_dataset_from_indicators_15m_scoreable_current`
- `training.v_rt_dataset_15m_from_unified_scoreable_current`

See `/Users/vitolo/Desktop/projects/poly/training_ready.md` for the current “safe” feature columns for these views.

## 3) How This Should Be Used to Train a Model (Operationally)

### Pick a dataset that matches the serving distribution
The review run explicitly flags **source/semantics mismatch risk**:

- Training OHLCV + features contain Binance-style columns (`taker_buy_*`, `num_trades`, `quote_volume`).
- Serving features in `indicators.*` are Coinbase-derived.

This can cause train/serve skew even if the offline accuracy looks good.

If the model is going to run on `indicators.v_model_15m` / `indicators.v_model_1h`, the cleanest approach is to train on RT-aligned views in `training.*` that are sourced from `indicators` (the `v_rt_dataset_from_indicators_*` family).

### Avoid leakage via event timing
For any “predict the candle outcome” task:

- Features must be computed from data available at decision time.
- Any feature that uses the future (even inside the same candle) will leak.

This is especially relevant if you build features from `training.spot_1m` around candle boundaries.

## 4) Ambiguities / Pitfalls Found (Do Not Ignore)

From the review run’s “Ambiguities / Skew Risks” section:

- Timestamp naming/grain differs across tables: `ts` (1m) vs `open_time` (15m/1h/unified).
- Training keys are `(symbol, open_time)`; serving keys are `(pair, bucket_time)`.
- Data types differ: training feature tables are mostly `double precision`, serving `indicators.v_model_*` is mostly `numeric`.
  - This is not “wrong”, but it matters for joins/casts and distribution comparisons.

Also noted as planned-but-empty (pipeline incomplete):
- `training.feature_matrix` and `training.event_labels` are empty.
- `training.polymarket_*` tables are present but empty.

## 5) Potentially Bad / Skewed Indicators (Flagged, Not Fixed)

The review run generated 120 quality flags across training tables (missingness, bounds violations, non-finite values, huge magnitude outliers, etc.).

Examples of flagged issues (non-exhaustive):

- `training.spot_1m`: high missingness in `obv`, `vwap`, `bb_middle`, `trendline_resistance`; bounds violations for `stoch_k`, `stoch_d`.
- `training.spot_15m_indicators`: bounds violations for `cmf_*`, stochastic variants, `williams_r_14`; `eom_14` not-finite / huge magnitude; `vortex_plus_14` / `vortex_minus_14` not-finite.

Full flagged list:
- `/Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/runs/20260210T160002Z/json/indicator_anomalies.json`

If we train a model, these flagged columns should be treated as “candidate exclusion list” until proven safe.

## 6) Do Training Names/Types Correlate With Serving Indicators?

The review run computed alignment against serving views:

### `training.unified_15m` vs `indicators.v_model_15m`
- Exact-name intersection: 33
- Training-only: 44
- Indicators-only: 81
- Type mismatches in the intersection: 33 (commonly `double precision` vs `numeric`)

### `training.unified_1h` vs `indicators.v_model_1h`
- Exact-name intersection: 31
- Training-only: 45
- Indicators-only: 50
- Type mismatches in the intersection: 31

Conclusion:
- There is meaningful overlap, but it is not a 1:1 match.
- If you want a training dataset that “drops in” to the serving contract, use the RT-aligned datasets in `training.*` derived from `indicators.*`.

## 7) Repro / How To Refresh This Report

Scripts live in:
- `/Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/`

Canonical runner:
- `/Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/run_all.py`

It writes timestamped artifacts under:
- `/Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/runs/<UTC_TIMESTAMP>/`

