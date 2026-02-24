# V3 Analysis: Alpha XGBoost Model

## Abstract

V3 represented the most ambitious iteration of the Polymarket prediction system—a proper machine learning implementation using XGBoost trained on relative, percentile-based features with walk-forward cross-validation. The validation metrics were impressive: 75–80% accuracy across all six models, with AUC scores reaching 0.888. The backtest period (Jan 26 – Feb 2, 2026) appeared to validate the approach, showing 69–85% accuracy on live-labeled data. 

However, the transition to true out-of-sample live trading (Feb 2–6, 2026) exposed a catastrophic failure: live accuracy collapsed to approximately 47%, performing worse than random chance on UP predictions (36–45%). This represents one of the most severe backtest-to-live gaps in the system's history—a decline of 30+ percentage points. The disaster was not a gradual degradation but an immediate, total breakdown, suggesting either fundamental overfitting despite walk-forward methodology, distribution shift in market microstructure, or critical architectural flaws in the feature pipeline.

This document performs a thorough post-mortem of V3, analyzing what worked, what failed, and why a methodologically sound approach produced such devastating real-world results.

---

## 1. Strategy Overview

### 1.1 Core Concept

V3 abandoned the threshold-based heuristic approach of previous versions in favor of a data-driven, machine learning-first paradigm:

- **Relative features, not absolute values**: All features were computed as percentile ranks, slopes, or regime flags rather than raw indicator values. This was intended to reduce sensitivity to asset-specific price scales and volatility regimes.
- **Walk-forward cross-validation**: The dataset was split into sequential folds with a fixed training window and advancing validation window, eliminating the look-ahead bias that plagued earlier versions.
- **Per-pair, per-timeframe models**: Six independent XGBoost classifiers were trained (BTC, ETH, SOL × 15m, 1h) to capture asset-specific price dynamics.
- **Confidence tiering**: Predictions were bucketed into HIGH (prob > 0.65), MED (0.58–0.65), and LOW (< 0.58) confidence tiers, with the hypothesis that HIGH confidence predictions would be significantly more accurate.

### 1.2 Market Targets

- **Assets**: BTC-USD, ETH-USD, SOL-USD
- **Timeframes**: 15-minute and 1-hour candles
- **Prediction horizon**: Next candle close direction (UP or DOWN)
- **Market**: Polymarket (crypto synthetic markets)
- **Training data window**: ~5 years of OHLCV + order book + CVD data

### 1.3 Risk Profile

The system was inherently risky:
- High-frequency predictions (every 15 minutes) with 2–4% average true price moves per candle
- Confidence in technical indicators despite known market efficiency challenges
- Reliance on blockchain data (CVD, volume) without understanding market microstructure
- No position sizing or risk management—each signal was treated independently

---

## 2. Implementation Architecture

### 2.1 Data Schema (alpha schema)

The system stored its models and predictions in a Supabase PostgreSQL database:

| Table | Purpose | Notes |
|-------|---------|-------|
| `models` | Model artifacts | XGBoost binary (pickled), training metadata |
| `features_15m` / `features_1h` | Precomputed indicators | Materialized feature vectors for all historical bars |
| `predictions_15m` / `predictions_1h` | Backtest predictions | Jan 26 – Feb 2 (labeled with actual outcomes) |
| `signals` | Live predictions | Feb 2 – Feb 6 (unlabeled, in real-time) |
| `model_performance` | Evaluation metrics | Empty (never populated) |
| `readme` | Documentation | Model notes and assumptions |

### 2.2 Feature Engineering (53 Features)

All features were computed in relative (percentile or derivative) space:

**Category 1: Percentile Ranks** (RSI, Stochastic, Price Position)
- `rsi_14_pct_20`, `rsi_14_pct_50`, `rsi_14_pct_100`: RSI percentile rank within 20, 50, 100-bar lookback
- `stoch_k_pct_20`, `stoch_k_pct_50`: Stochastic %K percentile rank
- Similar percentile ranks for price vs moving averages (SMA 20/50, EMA 21, Bollinger Bands)

**Category 2: Slopes & Momentum Derivatives** (5 features)
- `rsi_slope_3`, `rsi_slope_5`, `rsi_slope_10`: RSI change over 3, 5, 10 bars
- `macd_hist_slope_3`, `macd_hist_slope_5`: MACD histogram slope
- `adx_slope_5`: ADX (trend strength) slope

**Category 3: Regime Flags** (Binary)
- `is_oversold`, `is_overbought`: RSI < 30 or > 70
- `is_strong_trend`: ADX > 25
- `is_bullish_macd`, `is_bearish_macd`: MACD histogram sign
- Similar flags for Bollinger Band position, volume profile

**Category 4: Cross-Timeframe Features** (15m models only, 3 features)
- `rsi_15m_vs_1h`: RSI (15m) - RSI (1h) difference
- `trend_alignment_1h`: 1 if 15m and 1h trends agree, 0 otherwise
- `volatility_ratio_1h`: Volatility (15m) / Volatility (1h)

**Category 5: Temporal Encoding** (4 features)
- `hour_sin`, `hour_cos`: Sine/cosine encoding of hour-of-day (0–23)
- `dow_sin`, `dow_cos`: Sine/cosine encoding of day-of-week (0–6)
- `is_weekend`: Binary flag

**Category 6: Additional Momentum** (computed but specific features vary)
- Volume-weighted moving averages
- Cumulative volume delta (CVD) percentile rank
- True range and volatility measures

**Top 5 Features (by XGBoost importance)**:
1. `rsi_slope_3` — 3-bar RSI change
2. `is_bearish_macd` — Negative MACD histogram flag
3. `stoch_k_pct_20` — Stochastic %K percentile
4. `is_bullish_macd` — Positive MACD histogram flag
5. `rsi_14_pct_20` — RSI percentile rank

### 2.3 Model Specifications

**Algorithm**: XGBoost binary classifier
**Objective**: Binary logistic (probability of UP movement)
**Training**: Walk-forward cross-validation with 5 sequential folds
**Training window**: ~5 years of historical data, rolled forward

**Hyperparameters**:
- `max_depth=4` — Shallow trees to prevent overfitting
- `min_child_weight=50` — High minimum leaf size (conservative)
- `subsample=0.8` — 80% of rows sampled per tree
- `learning_rate=0.1`, `n_estimators=100` (inferred from performance)

**Confidence Thresholds** (predicted probability of UP):
- HIGH: prob > 0.65
- MED: 0.58 ≤ prob ≤ 0.65
- LOW: prob < 0.58

**Magnitude Formula** (for Polymarket market size):
```
magnitude = min(10, max(1, ((abs(prob - 0.5) * 2)^1.3) * 15))
```
This exponentially scales confidence (distance from 0.5) to a 1–10 range, clipped to Polymarket bet sizing.

### 2.4 Inference Pipeline

**Deployment**: Cloud Run (Serverless)
**Trigger**: Cloud Scheduler → pg_cron, every 15 minutes

**Execution flow**:
1. Fetch latest OHLCV candle for BTC, ETH, SOL (Binance or on-chain)
2. Compute all 53 features for 15m and 1h timeframes
3. Load pre-trained XGBoost models for each asset/timeframe
4. Generate predictions: probability of UP, confidence tier, magnitude
5. Log signals to `alpha.signals` table
6. (Intended) Execute Polymarket orders based on magnitude and tier

---

## 3. Validation & Backtest Results

### 3.1 Model Validation Metrics

**Walk-Forward Cross-Validation Results** (on out-of-sample validation folds):

| Model | Train Samples | Val Accuracy | Val AUC | HIGH Tier Accuracy | HIGH Tier % of Preds |
|-------|--------------|-------------|---------|-------------------|----------------------|
| BTC_15m | 222,821 | 75.0% | 0.833 | 76.4% | 75.3% |
| BTC_1h | 55,692 | 78.6% | 0.873 | 84.1% | 74.4% |
| ETH_15m | 222,825 | 76.1% | 0.845 | 80.4% | 71.1% |
| ETH_1h | 55,693 | 79.3% | 0.880 | 83.8% | 73.1% |
| SOL_15m | 188,269 | 76.9% | 0.851 | 80.9% | 73.2% |
| SOL_1h | 47,052 | 80.5% | 0.888 | 84.3% | 75.1% |

**Interpretation**: 
- Validation accuracies ranged 75–80%, well above 50% random baseline
- AUC scores (0.833–0.888) indicated strong discriminative power
- HIGH confidence tier showed 76–84% accuracy, suggesting the confidence calibration worked on validation data
- 70–75% of predictions fell into HIGH tier, indicating aggressive confidence

### 3.2 Backtest Period (Jan 26 – Feb 2, 2026)

Backtest predictions were labeled with actual market outcomes *after* the candle closed. This window represented the system's "final test" before deploying to live trading.

**15-minute predictions** (1,832 total signals):

| Asset | Direction | Count | Accuracy |
|-------|-----------|-------|----------|
| BTC | DOWN | 340 | 79.35% |
| BTC | UP | 268 | 75.37% |
| ETH | DOWN | 350 | 75.36% |
| ETH | UP | 262 | 77.86% |
| SOL | DOWN | 359 | 83.84% |
| SOL | UP | 253 | 69.44% |

**1-hour predictions** (461 total signals):

| Asset | Direction | Count | Accuracy |
|-------|-----------|-------|----------|
| BTC | DOWN | 83 | 85.37% |
| BTC | UP | 70 | 78.57% |
| ETH | DOWN | 90 | 80.90% |
| ETH | UP | 64 | 78.13% |
| SOL | DOWN | 81 | 76.25% |
| SOL | UP | 73 | 71.23% |

**Observations**:
- 15m predictions: 75–84% accuracy (DOWN slightly better than UP on BTC/SOL)
- 1h predictions: 71–85% accuracy (stronger, fewer samples)
- DOWN predictions consistently outperformed UP predictions
- Results appeared to justify proceeding to live deployment

---

## 4. Live Period Collapse (Feb 2–6, 2026)

### 4.1 Live Predictions — The Failure

On Feb 2, 2026, 12:20 UTC, the system transitioned to live trading. Predictions were no longer labeled against actual outcomes—the system was predicting real market moves in real-time for actual Polymarket positions.

**15-minute signals** (1,494 predictions, Feb 2–6):

| Asset | Direction | Count | Accuracy |
|-------|-----------|-------|----------|
| BTC | DOWN | 206 | 51.94% |
| BTC | UP | 192 | 43.46% |
| ETH | DOWN | 220 | 48.18% |
| ETH | UP | 178 | 44.63% |
| SOL | DOWN | 217 | 50.46% |
| SOL | UP | 181 | 38.12% |

**1-hour signals** (300 predictions, Feb 2–6):

| Asset | Direction | Count | Accuracy |
|-------|-----------|-------|----------|
| BTC | DOWN | 50 | 50.00% |
| BTC | UP | 50 | 36.73% |
| ETH | DOWN | 49 | 59.18% |
| ETH | UP | 51 | 42.00% |
| SOL | DOWN | 53 | 52.83% |
| SOL | UP | 47 | 45.65% |

### 4.2 Magnitude of Failure

**Accuracy gap (backtest → live)**:
- BTC 15m DOWN: 79.35% → 51.94% (−27.4 pp)
- ETH 15m DOWN: 75.36% → 48.18% (−27.2 pp)
- SOL 15m DOWN: 83.84% → 50.46% (−33.4 pp)
- BTC UP: 75.37% → 43.46% (−31.9 pp)
- ETH UP: 77.86% → 44.63% (−33.2 pp)
- SOL UP: 69.44% → 38.12% (−31.3 pp)

**UP predictions were catastrophic**: 36–45% accuracy, approaching coin-flip performance (50%) or worse. The model was **systematically wrong** on bullish predictions.

### 4.3 Known Issues During Live Period

#### Issue 1: CVD Stale Period (Feb 2, 04:37–12:20 UTC)

The Cumulative Volume Delta (CVD) indicator, one of the model's input features, failed to update during a 7-hour 43-minute window. The CVD value froze at **−332.0972** across all candles in this period.

**Impact on HIGH confidence tier**:
- During stale period: HIGH confidence predictions dropped to **33.3% accuracy** (expected 83–85%)
- This represents an **inverted** signal—the model's highest confidence was most wrong
- The freeze affected hundreds of predictions across all three assets

**Remediation**: CVD data was later backfilled from Binance volume data, but the damage to the early live period was already done.

**Implications**:
- The model was heavily reliant on CVD despite it being an unreliable data source
- HIGH confidence tier inverted during data corruption, suggesting the model learned brittle, non-robust patterns

#### Issue 2: Market Regime Shift (Feb 2–6)

The period Feb 2–6, 2026 may have experienced a fundamentally different market regime than the training/backtest period:
- Different volatility regime
- Different trend microstructure
- Different liquidity and volume patterns
- Possible impact event or market shock during this window

The training data spanned ~5 years, but the features (RSI, MACD, Stochastic) are short-term indicators. If the broader market regime shifted, feature distributions would change, and the model would extrapolate poorly.

---

## 5. Technical Deep Dive: Why It Failed

### 5.1 Hypothesis 1: Massive Overfitting Despite Walk-Forward CV

Walk-forward cross-validation is designed to prevent look-ahead bias, but it does **not** prevent overfitting if the feature engineering itself contains look-ahead information.

**Suspected culprit**: The feature computation pipeline may have introduced temporal leakage:
- Percentile ranks are computed using a lookback window (e.g., RSI percentile within last 20 bars)
- These percentiles are then used as inputs to a model trained on historical data
- If the model was trained on the same bars used to compute the percentile windows, there is **implicit look-ahead bias**

**Example**: To compute `rsi_14_pct_20` for bar T, you need RSI values from bars [T-19 to T]. If the model is trained on bars where bar T is the target (label), and the feature includes bar T itself, this is look-ahead.

**Evidence**: 
- Validation accuracy 75–80%, backtest 75–84%, live 47%
- The backtest used the same feature vectors as the model was trained on (computed from the same data)
- As soon as the system moved to truly novel data (live), accuracy collapsed

### 5.2 Hypothesis 2: Feature Distribution Shift / Market Regime Change

The training data spanned ~5 years (likely 2021–2026). The live period (Feb 2–6, 2026) may have been in a statistical regime far from the training distribution:

**Potential shifts**:
- **Volatility regime**: If the market was unusually quiet or volatile, the percentile-based features would behave differently
- **Trend structure**: If the market shifted from trending to mean-reverting (or vice versa), indicator slopes would become unreliable
- **Volume pattern**: If trading volume shifted, CVD and volume-weighted indicators would diverge from historical norms
- **Correlation structure**: If asset correlations changed (e.g., SOL decoupling from BTC), cross-timeframe features would be misleading

The model had no mechanism to detect regime shifts or adapt to distribution changes. It assumed the live market would resemble the training distribution.

### 5.3 Hypothesis 3: UP vs. DOWN Label Imbalance

Throughout backtest and live results, UP predictions consistently underperformed DOWN predictions:
- Backtest: BTC UP 75.37%, BTC DOWN 79.35% (4% gap)
- Live: BTC UP 43.46%, BTC DOWN 51.94% (8.5% gap)

This suggests:
1. **Class imbalance in training data**: If the training set had more DOWN labels than UP labels, the model would learn biased decision boundaries
2. **Asymmetric market behavior**: Markets may move down more decisively than they move up (or the reverse), encoded in the data
3. **Confidence calibration failure**: The thresholds (0.65, 0.58) may be inappropriately tuned for the UP class

The 1-hour models showed even worse UP performance (36–45%), indicating the bias was severe for shorter-window predictions.

### 5.4 Hypothesis 4: Indicator Lookback Window Leakage

Technical indicators (RSI, MACD, Stochastic, ADX) are computed using lookback windows:
- RSI: 14-bar window
- MACD: 12/26-bar exponential moving averages
- ADX: 14-bar rolling window
- Bollinger Bands: 20-bar SMA + 2σ

If the model predicts the next candle (bar T+1) using indicators computed from bars [0 to T], the indicators legitimately use bar T data. **However**, the walk-forward validation itself may not respect these lookback dependencies properly.

**Example of the bug**:
- Walk-forward fold 1: Train on bars 0–1000, validate on bars 1001–1100
- When computing indicators for bar 1001, use bars [987–1000] for the 14-bar lookback
- But bars 987–1000 were part of the training fold!
- This means validation accuracy includes implicit training data influence through indicator lookback windows

### 5.5 Hypothesis 5: CVD Unreliability

Cumulative Volume Delta (CVD) was among the top features, yet:
- It failed completely for 7+ hours (froze at −332.0972)
- During the freeze, HIGH confidence predictions inverted to 33.3% accuracy
- CVD requires high-quality on-chain volume data, which may be noisy, subject to manipulation, or unreliable on certain exchanges

The model learned to rely on CVD without understanding its fragility.

### 5.6 Hypothesis 6: Temporal Leakage in Walk-Forward CV

Walk-forward CV with a fixed training window may still leak information if the feature indicators have implicit memory:

**Scenario**:
- Fold 1: Train on bars 0–1000, validate on bars 1001–1100
- Fold 2: Train on bars 250–1250, validate on bars 1251–1350
- Fold 3: Train on bars 500–1500, validate on bars 1501–1600
- ...
- Fold 5: Train on bars 2000–3000, validate on bars 3001–3100

When fold 5 is validated on bars 3001–3100, the features for these bars depend on indicators computed from bars 2987–3100 (for a 14-bar lookback RSI). Bars 2987–3000 were part of the training set, so their influence propagates into validation features.

This is subtle but pervasive—the model never truly sees out-of-distribution data if the indicator lookback windows are long enough.

---

## 6. Known Unknowns & Data Quality Issues

### 6.1 CVD Stale Period

- **Dates**: Feb 2, 04:37–12:20 UTC (7h 43m)
- **Cause**: Unknown (likely upstream data source failure)
- **Value**: Frozen at −332.0972 for all candles
- **Affected signals**: ~400–500 predictions in early live period
- **HIGH tier accuracy during freeze**: 33.3% (should be 83–85%)
- **Remediation**: Manual backfill from Binance volume data (post-hoc, doesn't help live performance)

### 6.2 Model Binary Serialization

The XGBoost models were stored as pickled Python objects in the database. Questions remain:
- Were all 6 models successfully serialized and deserialized?
- Did the Cloud Run inference environment have the correct XGBoost version?
- Were there any silent deserialization failures that caused fallback behavior?

**Evidence sought but not found**: No error logs from model loading in Cloud Run.

### 6.3 Feature Computation Bugs

The feature pipeline was complex (53 features × 6 models × every 15 minutes). Potential issues:
- Off-by-one errors in indicator computation
- Incorrect lookback windows (e.g., 20-bar vs. 21-bar)
- Division by zero or null handling in percentile ranks
- Missing data handling during weekends or gaps

**Verification status**: Unknown (no unit tests found, no feature sanity checks in logs).

---

## 7. Lessons Learned

### 7.1 What Worked (Sort Of)

#### Feature Engineering Approach: Relative > Absolute
The shift to relative, percentile-based features was methodologically sound:
- Removed asset-specific price scales (BTC ~$40K, SOL ~$140)
- Made indicators more stationary (percentile ranks are bounded)
- Reduced sensitivity to multi-year drift

This approach was better than earlier versions' absolute value thresholds.

#### Walk-Forward Cross-Validation Framework
The methodology was correct:
- No look-ahead bias in the *conceptual* design
- Sequential folds matched real-time deployment
- Provided honest(ish) estimate of out-of-sample performance

The execution, however, was likely flawed (see lookback leakage above).

#### Confidence Tiering
The hypothesis that HIGH confidence predictions would be more accurate was sound *in validation*:
- HIGH tier: 76–84% accuracy on validation data
- MED/LOW tiers: presumably lower (not reported)

This suggested the model learned to calibrate its uncertainty appropriately—until live trading began.

### 7.2 What Didn't Work (Critical Failures)

#### 1. Catastrophic Backtest-to-Live Gap (75–80% → 47%)

This is the core failure. A 30+ percentage point drop in accuracy is unrecoverable. Possible causes:
- **Overfitting through temporal/feature leakage** (most likely)
- **Distribution shift** (market regime change Feb 2–6)
- **Label bias** (more DOWN than UP in training set)
- **Feature quality degradation** (CVD freeze, data sources)

The gap suggests the backtest was not a true out-of-sample test. The model memorized patterns in the backtest data that don't generalize.

#### 2. UP Predictions Inverted (36–45% Accuracy)

The model systematically predicted DOWN movements and was wrong. UP predictions were at coin-flip or worse performance:
- BTC UP: 43.46% (live) vs. 75.37% (backtest) → **−31.9 pp**
- ETH UP: 44.63% (live) vs. 77.86% (backtest) → **−33.2 pp**
- SOL UP: 38.12% (live) vs. 69.44% (backtest) → **−31.3 pp**

This indicates:
- The model learned inverted patterns for UP movements
- Or it learned DOWN patterns that happened to work in backtest but inverted in live
- Or label encoding was inconsistent between backtest and live

#### 3. HIGH Confidence Tier Inversion During CVD Freeze

When CVD data froze (Feb 2, 04:37–12:20), the HIGH confidence predictions inverted from ~84% accuracy to ~33%:
- This is not random degradation—it's a **sign reversal**
- Suggests the model learned a brittle dependency on CVD
- The HIGH confidence tier became the highest-risk tier during data corruption

This reveals fundamental architectural fragility.

#### 4. No Adaptive Mechanism for Regime Change

The model was trained on 5 years of data but had no mechanism to detect if the market regime shifted. Possible regime changes Feb 2–6:
- Volatility structure
- Trend vs. mean-reversion balance
- Liquidity and volume patterns
- Correlation structure (BTC-ETH-SOL co-movement)

A robust system would have:
- Real-time distribution monitoring
- Model retraining or adaptation triggers
- Fallback logic when feature distributions diverge from training

None of this existed in V3.

#### 5. Unvalidated Data Leakage in Walk-Forward CV

While the conceptual design was sound, the execution likely contained subtle temporal leakage:
- 14-bar indicator lookbacks in validation data included bars from training folds
- Backtest predictions may have used the same feature vectors as training
- No explicit guards against this during implementation

The fact that backtest (75–84%) matched validation (75–80%) perfectly is suspicious—true out-of-sample performance should be more variable.

#### 6. Label Imbalance and Asymmetric Learning

The consistent DOWN > UP pattern suggests:
- Training set had more DOWN labels
- Model learned biased decision boundaries
- Confidence thresholds (0.65, 0.58) were not calibrated for class balance

No class weighting or balanced sampling was applied.

#### 7. Fragile Feature Pipeline

The feature computation was complex (53 features, 6 categories, multiple lookback windows) without:
- Unit tests
- Sanity checks (e.g., "percentile rank should be 0–1")
- Monitoring for NaN/null/stale values
- Explicit handling of edge cases (market close, low liquidity)

The CVD freeze was the symptom; the underlying fragility was the disease.

---

## 8. What Should Have Been Done Differently

### 8.1 Validation & Testing

1. **Stricter walk-forward validation**:
   - Explicit check: Validation fold indicators use *only* bars from validation fold, not training fold lookback windows
   - Separate "feature computation data" from "model training data" timelines
   - Multiple seeds/shuffles to verify robustness

2. **Live paper trading before real deployment**:
   - Simulate live conditions with truly novel data (March 2026 data trained on Jan-Feb 2026 backtest)
   - Compare paper vs. backtest to catch distribution shifts

3. **Benchmarking against baselines**:
   - Random forest with same features
   - Logistic regression (linear model, high bias, low variance)
   - Seasonal naive baseline (e.g., "SOL usually goes UP on Sundays")
   - Simple momentum threshold model

4. **Class balance analysis**:
   - Stratified k-fold with explicit class balance metrics
   - Report precision, recall, F1-score (not just accuracy)
   - Use `class_weight='balanced'` in XGBoost

### 8.2 Feature Engineering

1. **Decouple indicator computation from model training**:
   - Compute indicators from a frozen historical window (e.g., all data before Jan 1, 2026)
   - Train model on computed features with explicit temporal separation
   - This prevents lookback window leakage

2. **Feature importance validation**:
   - Top 5 features: rsi_slope_3, is_bearish_macd, stoch_k_pct_20, is_bullish_macd, rsi_14_pct_20
   - Do these correlate with actual next-candle returns *at all*? (Check basic correlation)
   - Are they stable across different market regimes?

3. **Robustness checks**:
   - Permutation feature importance (shuffle each feature, measure accuracy drop)
   - Feature redundancy analysis (drop highly correlated features)
   - Stress test: What happens if CVD is completely removed? (Should see graceful degradation, not collapse)

4. **Real-time monitoring**:
   - Log feature distributions on each 15-minute inference
   - Compare live feature statistics to training distribution (Kolmogorov-Smirnov test, KL divergence)
   - Alert if distributions diverge significantly

### 8.3 Model Architecture

1. **Ensemble of models**:
   - Train 3–5 XGBoost models with different random seeds and hyperparameters
   - Average their predictions
   - Use variance across ensemble as additional uncertainty quantifier

2. **Model retraining schedule**:
   - Retrain models weekly on rolling 1-year window
   - Test if newer data improves live performance
   - This is standard in production ML

3. **Fallback logic**:
   - If any feature becomes stale (CVD, volume), set confidence to LOW
   - If live accuracy drops below 52% over last 100 predictions, issue alert
   - Halt trading if multiple data quality issues detected

4. **Simpler model for comparison**:
   - Train a logistic regression model on same features
   - If logistic regression outperforms XGBoost on live data, XGBoost is overfitting

### 8.4 Operational

1. **Monitoring dashboard**:
   - Live accuracy on recent 100/500/1000 predictions
   - Feature distribution heatmap
   - Data freshness check (when was CVD, volume, etc. last updated)
   - Alert thresholds for accuracy drops

2. **Data quality pipeline**:
   - Validate all feature values before inference (NaN check, range check, etc.)
   - Log reasons for any NaN (data source failure, processing bug, etc.)
   - Gracefully degrade if a feature is unavailable

3. **Prediction audit log**:
   - Log every prediction: timestamp, asset, timeframe, all 53 feature values, predicted prob, confidence tier, magnitude, actual outcome
   - Enable post-hoc analysis of failure patterns

---

## 9. Post-Mortem Summary

### What Went Wrong

V3 failed due to a combination of:

1. **Overfitting disguised as validation** (70–80%): The walk-forward CV was conceptually correct but likely contained temporal leakage through indicator lookback windows. The backtest results perfectly matched validation results, suggesting the test was not truly out-of-sample.

2. **Distribution shift without adaptation** (Feb 2–6 regime change): The model was not robust to market regime changes. No mechanism existed to detect if the live market differed from training conditions.

3. **Label imbalance and asymmetric learning**: UP predictions were consistently worse (31–33% worse in backtest-to-live gap). This suggests the training set had more DOWN labels, or the model learned inverted patterns.

4. **Fragile feature pipeline** (CVD freeze): A single data source failure (CVD freeze for 7+ hours) caused HIGH confidence predictions to invert (84% → 33%). This revealed the model was brittle and dependent on unreliable upstream data.

5. **No real-world testing before deployment**: The backtest was too similar to the training process. True out-of-sample testing (paper trading on wholly novel data) would have caught these issues.

### The Numbers

- **Validation accuracy**: 75–80% (walk-forward CV)
- **Backtest accuracy**: 75–84% (labeled Jan 26 – Feb 2)
- **Live accuracy**: 47% average, DOWN 50–52%, UP 36–45% (Feb 2–6)
- **Backtest-to-live gap**: −27 to −34 percentage points

This is a catastrophic failure for a production system.

### Why It Matters

V3 represents a critical inflection point: the shift from rule-based to data-driven. The infrastructure was sound (Cloud Run, walk-forward CV, 6 models, proper validation framework). But the execution had invisible flaws—temporal leakage, overfitting, and brittleness—that only revealed themselves in live trading.

The lesson is that *methodologically correct approaches can still fail* if implementation details are sloppy. Walk-forward validation does not prevent all forms of data leakage. Validation metrics do not guarantee live performance. An impressive-looking backtest can be a mirage.

### Path Forward

For any V4 or successor:

1. **Validate the validator**: Ensure walk-forward CV truly prevents look-ahead by checking indicator computation independence
2. **Test on truly novel data**: Use March 2026 + data (or future data) to validate, not Jan 26 – Feb 2
3. **Monitor live performance in real-time** with automated alerts
4. **Implement graceful degradation**: When data quality drops or regime shifts, reduce position size or halt trading
5. **Keep baselines**: Always compare against a simple rule-based model to catch overfitting
6. **Embrace uncertainty**: Use ensemble models and confidence intervals, not point predictions

V3 failed, but the failure is instructive. The path to a robust prediction system requires obsessive attention to data quality, rigorous separation of training/validation/test data, and real-time monitoring for distribution shift.

---

## Appendix: Feature List (Complete)

**53 Features for 15m Models** (50 features for 1h models, lacking the 3 cross-timeframe features):

### Percentile Ranks (12 features)
- `rsi_14_pct_20`, `rsi_14_pct_50`, `rsi_14_pct_100`
- `stoch_k_pct_20`, `stoch_k_pct_50`
- `price_vs_sma_20_pct`, `price_vs_sma_50_pct`
- `price_vs_ema_21_pct`
- `price_vs_bb_mid_pct`
- `bb_position` (0–1, relative position between lower and upper band)
- `cvd_pct_rank`

### Slopes & Derivatives (5 features)
- `rsi_slope_3`, `rsi_slope_5`, `rsi_slope_10`
- `macd_hist_slope_3`, `macd_hist_slope_5`
- `adx_slope_5`

### Regime Flags (Binary, ~15 features)
- `is_oversold` (RSI < 30)
- `is_overbought` (RSI > 70)
- `is_strong_trend` (ADX > 25)
- `is_bullish_macd`, `is_bearish_macd`
- `is_bullish_stoch` (Stoch < 20 = oversold → bullish), `is_bearish_stoch`
- `bb_upper_touch`, `bb_lower_touch`, `bb_mid_cross`
- `high_volume_bar` (volume > 95th percentile)
- `large_candle` (true range > 95th percentile)

### Cross-Timeframe Features (3 features, 15m only)
- `rsi_15m_vs_1h` (difference in RSI values between timeframes)
- `trend_alignment_1h` (1 if 15m and 1h trend agree)
- `volatility_ratio_1h` (volatility 15m / volatility 1h)

### Temporal Encoding (4 features)
- `hour_sin`, `hour_cos` (sine/cosine of hour 0–23)
- `dow_sin`, `dow_cos` (sine/cosine of day 0–6)
- `is_weekend` (binary)

### Additional Momentum/Volume (remaining ~13 features)
- Volume-weighted RSI
- Volume-weighted momentum
- Volume MA ratios
- Bid-ask spread proxies (if available)
- On-chain metrics (if available)
- Additional moving average crosses

---

## References & Methodology Notes

- **XGBoost paper**: Chen & Guestrin (2016), "XGBoost: A Scalable Tree Boosting System"
- **Walk-forward cross-validation**: Bergmeir & Benítez (2012), "On the use of cross-validation for time series predictor evaluation"
- **Technical indicators**: Standard definitions (RSI, MACD, ADX, Bollinger Bands, Stochastic Oscillator)
- **Cryptocurrency data**: OHLCV from Binance, order book data, blockchain CVD from on-chain indexers

---

**Document Version**: 1.0  
**Date**: February 6, 2026  
**Status**: Post-mortem / Archived  
**Recommendation**: V3 should not be used for any production trading. The failure to generalize to live data is irredeemable without fundamental redesign.
