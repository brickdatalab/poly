# V5 Architecture: Unified 1-Hour Prediction System

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a profitable 1-hour directional crypto predictor (BTC/ETH/SOL) with continuous online learning, zero training-serving skew, and automated Polymarket execution.

**Architecture:** Single Python process on GCP VM. One feature computation function used for both training and inference. XGBoost with online incremental updates. Signal validation before any model is deployed.

**Tech Stack:** Python 3.11, XGBoost, pandas, Supabase (Postgres), GCP Compute Engine, py-clob-client (Polymarket)

---

## 1. Why V1-V4 Failed (TL;DR)

| Root Cause | Versions Affected | V5 Fix |
|---|---|---|
| Wrong tool (LLM for prediction) | V1 | XGBoost on proper features |
| Static thresholds, no adaptation | V1, V2 | Continuous online retraining |
| Training-serving skew | V3, V4 | Single `compute_features()` function |
| Temporal leakage in CV | V3 | Proper embargo gaps in walk-forward |
| Curse of dimensionality (272 features) | V4 | Start with ~12 features, prove each one |
| No signal validation before deployment | V3, V4 | Phase 0: prove signal exists first |
| No regime awareness | All | Volatility regime gating |

---

## 2. Data Inventory (What We Already Have)

### Historical Training Data
- **`training.spot_1h`**: ~55K rows per BTC/ETH, ~47K for SOL (2019-09 to 2026-02-01)
  - Columns: symbol, open_time, OHLCV, quote_volume, num_trades, taker_buy_base_vol, taker_buy_quote_vol, label, pct_change, pct_change_zscore, high_low_range, upper_wick_pct, lower_wick_pct
  - **Labels already computed** (label column = UP/DOWN based on close > open)

### Live OHLCV
- **`indicators.ohlcv_1h`**: 373 candles per pair (Jan 22 - Feb 6, 2026, live streaming)
  - Columns: pair, bucket_time, open, high, low, close, volume

### Live Indicators
- **`indicators.indicator_values`**: 46 active 1h configs, ~14K rows per pair
  - Coverage: Jan 25 - Feb 6, 2026 only (NOT historical)
  - Categories: trend (6), oscillator (9), volatility (7), volume (8), moving_average (10), complex (5)

### Key Insight
We have 5+ years of OHLCV history but only 2 weeks of pre-computed indicators.

**V5 solution: Compute ALL features from OHLCV in Python.** This means the exact same `compute_features()` function runs on both historical data (training) and live candles (inference). Zero skew by construction.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     GCP VM (e2-standard-4)                  │
│                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ Data Ingest │───>│  Feature Eng │───>│   Inference   │  │
│  │  (hourly)   │    │  (SAME fn)   │    │  + Execution  │  │
│  └─────────────┘    └──────────────┘    └───────────────┘  │
│         │                  │                    │           │
│         │                  │                    │           │
│  ┌──────▼──────────────────▼────────────────────▼────────┐ │
│  │              Supabase (Postgres 17)                    │ │
│  │  v5.ohlcv_1h │ v5.features │ v5.predictions │ v5.model│ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─────────────┐    ┌──────────────┐                       │
│  │  Retrainer  │───>│  Model       │                       │
│  │  (hourly)   │    │  Registry    │                       │
│  └─────────────┘    └──────────────┘                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Polymarket CLOB Client (py-clob-client)            │   │
│  │  Execute trades when confidence > threshold          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Core Loop (runs every hour at :00)

```
1. Fetch latest 1h candle from Binance API (or Supabase live OHLCV)
2. compute_features(latest_candles)  ← SAME function as training
3. model.predict(features) → probability, direction, confidence
4. Log prediction to v5.predictions
5. IF confidence > threshold AND regime != "chaotic":
     → Execute trade via Polymarket CLOB API
6. Wait for outcome (1 hour)
7. Score prediction, update performance log
8. IF enough new data accumulated:
     → Retrain model on expanding window
     → Compare new model vs current on holdout
     → Swap if better (champion-challenger)
```

---

## 4. Feature Engineering (The Heart of V5)

### Design Principles
- **12 features max** to start (V3 had 53, V4 had 272 — both worse than V2's ~5)
- **Every feature computed from OHLCV only** — no external dependencies that can freeze/stale
- **Same function for training and live** — zero skew by construction
- **All features use ONLY prior bars** — no current-bar leakage

### Candidate Features (12 Starter Set)

| # | Feature | Category | Rationale |
|---|---------|----------|-----------|
| 1 | `rsi_14` | Oscillator | V3's top predictor (rsi_slope_3). Mean-reversion signal |
| 2 | `rsi_slope_3` | Momentum | 3-bar slope of RSI — rate of change of momentum |
| 3 | `macd_histogram` | Trend | Directional momentum. V3 found `is_bearish_macd` predictive |
| 4 | `bb_position` | Volatility | Price position within Bollinger Bands (0-1 normalized) |
| 5 | `atr_ratio` | Volatility | ATR(14) / close — normalized volatility for regime detection |
| 6 | `volume_ratio` | Volume | Current volume / SMA(20) volume — participation signal |
| 7 | `close_vs_ema21` | Trend | (close - EMA21) / ATR — trend strength normalized by vol |
| 8 | `stoch_k` | Oscillator | Stochastic %K(14,3) — oversold/overbought |
| 9 | `adx_14` | Trend | Trend strength — know when NOT to predict (low ADX = choppy) |
| 10 | `hour_sin` | Temporal | sin(2π * hour/24) — time-of-day cyclical encoding |
| 11 | `hour_cos` | Temporal | cos(2π * hour/24) — time-of-day cyclical encoding |
| 12 | `pct_change_1` | Price | Prior bar return — simple momentum/mean-reversion |

### `compute_features()` — The Single Source of Truth

```python
import pandas as pd
import numpy as np

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute V5 features from OHLCV data.

    CRITICAL: This EXACT function is used for BOTH training AND live inference.
    Input: DataFrame with columns [open, high, low, close, volume] indexed by time.
    Output: DataFrame with feature columns, NaN rows at top stripped.

    All computations use ONLY prior bars (shift(1) or rolling with closed='left').
    """
    f = pd.DataFrame(index=df.index)

    # --- Price features (lagged) ---
    f['pct_change_1'] = df['close'].pct_change().shift(1)

    # --- RSI(14) ---
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    f['rsi_14'] = rsi.shift(1)

    # --- RSI Slope (3-bar) ---
    f['rsi_slope_3'] = rsi.diff(3).shift(1)

    # --- MACD Histogram ---
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    f['macd_histogram'] = (macd_line - signal_line).shift(1)

    # --- Bollinger Band Position ---
    sma20 = df['close'].rolling(20).mean()
    std20 = df['close'].rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    f['bb_position'] = ((df['close'] - bb_lower) / (bb_upper - bb_lower)).shift(1)

    # --- ATR Ratio (normalized volatility) ---
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    f['atr_ratio'] = (atr14 / df['close']).shift(1)

    # --- Volume Ratio ---
    vol_sma20 = df['volume'].rolling(20).mean()
    f['volume_ratio'] = (df['volume'] / vol_sma20.replace(0, np.nan)).shift(1)

    # --- Close vs EMA21 (normalized by ATR) ---
    ema21 = df['close'].ewm(span=21, adjust=False).mean()
    f['close_vs_ema21'] = ((df['close'] - ema21) / atr14.replace(0, np.nan)).shift(1)

    # --- Stochastic %K ---
    low14 = df['low'].rolling(14).min()
    high14 = df['high'].rolling(14).max()
    raw_k = 100 * (df['close'] - low14) / (high14 - low14).replace(0, np.nan)
    f['stoch_k'] = raw_k.rolling(3).mean().shift(1)

    # --- ADX(14) ---
    plus_dm = df['high'].diff().clip(lower=0)
    minus_dm = (-df['low'].diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    plus_di = 100 * plus_dm.rolling(14).mean() / atr14.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(14).mean() / atr14.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    f['adx_14'] = dx.rolling(14).mean().shift(1)

    # --- Temporal (hour of day, cyclical) ---
    hour = df.index.hour if hasattr(df.index, 'hour') else pd.to_datetime(df.index).hour
    f['hour_sin'] = np.sin(2 * np.pi * hour / 24)
    f['hour_cos'] = np.cos(2 * np.pi * hour / 24)

    return f

FEATURE_COLUMNS = [
    'pct_change_1', 'rsi_14', 'rsi_slope_3', 'macd_histogram',
    'bb_position', 'atr_ratio', 'volume_ratio', 'close_vs_ema21',
    'stoch_k', 'adx_14', 'hour_sin', 'hour_cos'
]
```

### Why These 12 and Not Others

- **RSI, MACD, Stochastic**: V3 feature importance analysis showed `rsi_slope_3`, `is_bearish_macd`, `stoch_k_pct_20` were top-5 predictors
- **BB Position, ATR Ratio**: Volatility context — know when the market is ranging vs trending
- **ADX**: Explicit trend-strength gating — V2's ADX gate was its best innovation
- **Volume Ratio**: Participation signal — high volume = more conviction behind moves
- **Close vs EMA21**: Normalized trend position — how far from the mean, scaled by volatility
- **Hour Sin/Cos**: Time-of-day effect (Asian/European/US session dynamics)
- **Prior bar return**: Simple momentum/mean-reversion baseline

### Feature Expansion Protocol (Later)

After proving the 12-feature model works live, features can be added **one at a time** with statistical validation:
1. Add candidate feature to compute_features()
2. Retrain model on identical data split
3. Compare AUC before/after on HOLDOUT set
4. Only keep if improvement > 0.5 AUC points AND live validation confirms

---

## 5. Model Design

### Algorithm: XGBoost Binary Classifier

Why XGBoost (not ensemble, not neural net):
- V3 got 75-80% validation with XGBoost alone (better than V4's ensemble at 62-65%)
- Simple. One model to debug, one model to explain.
- Fast training (<1 min on 55K rows) — essential for continuous retraining
- Built-in feature importance — instant feedback on what matters

### Hyperparameters (Conservative Defaults)

```python
PARAMS = {
    'objective': 'binary:logistic',
    'eval_metric': 'auc',
    'max_depth': 3,          # Shallow trees — prevent overfitting (V3 used 4)
    'min_child_weight': 100,  # High — prevent fitting to noise (V3 used 50)
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'learning_rate': 0.05,    # Slow learning — better generalization
    'n_estimators': 200,
    'reg_alpha': 0.1,         # L1 regularization
    'reg_lambda': 1.0,        # L2 regularization
    'random_state': 42
}
```

### Walk-Forward Validation (With Proper Embargo)

```
Historical Data: 2019-09 ──────────────────────────────── 2026-02

Split 1: [═══TRAIN══════]__EMBARGO__[=VAL=]
Split 2:    [═══TRAIN══════]__EMBARGO__[=VAL=]
Split 3:       [═══TRAIN══════]__EMBARGO__[=VAL=]
...
Split N:                    [═══TRAIN══════]__EMBARGO__[=VAL=]

EMBARGO = 48 hours (2x prediction horizon)
         Prevents indicator lookback windows from leaking across boundary.
         V3's failure: 14-bar RSI lookback in val fold used training bars.
         With 48h embargo on 1h candles, the last 48 training bars are
         discarded before validation begins.
```

```python
def walk_forward_splits(
    timestamps: pd.DatetimeIndex,
    train_months: int = 6,
    val_months: int = 1,
    step_months: int = 1,
    embargo_hours: int = 48
) -> list[tuple]:
    """Generate walk-forward splits with temporal embargo."""
    splits = []
    start = timestamps.min()
    end = timestamps.max()

    current = start
    while True:
        train_end = current + pd.DateOffset(months=train_months)
        embargo_end = train_end + pd.Timedelta(hours=embargo_hours)
        val_end = embargo_end + pd.DateOffset(months=val_months)

        if val_end > end:
            break

        train_mask = (timestamps >= current) & (timestamps < train_end)
        val_mask = (timestamps >= embargo_end) & (timestamps < val_end)

        splits.append((train_mask, val_mask))
        current += pd.DateOffset(months=step_months)

    return splits
```

### Confidence Calibration

V4's biggest failure: 0.22-0.36 calibration error (model said 80% confidence → actual 44% accuracy).

V5 uses **Platt scaling** (logistic calibration on validation set):

```python
from sklearn.calibration import CalibratedClassifierCV

# After training XGBoost on train set:
calibrated_model = CalibratedClassifierCV(
    model, method='sigmoid', cv='prefit'
)
calibrated_model.fit(X_val, y_val)  # Calibrate on validation set
```

### Confidence Tiers and Execution Rules

| Tier | Probability Range | Action |
|------|------------------|--------|
| SKIP | 0.45 - 0.55 | No prediction (too close to 50/50) |
| LOW | 0.55 - 0.60 | Log prediction, NO trade |
| MEDIUM | 0.60 - 0.65 | Trade with 0.5x position size |
| HIGH | 0.65+ | Trade with 1x position size |

The SKIP zone is critical — V3/V4 forced predictions on every bar. V5 should only bet when there's actual edge.

---

## 6. Continuous Online Learning

### Strategy: Expanding Window Retraining

Every N hours (default: 24), the system:

1. **Collects new labeled data** (predictions from last 24h now have outcomes)
2. **Expands training window** (adds new data, doesn't drop old)
3. **Trains challenger model** on expanded data
4. **Compares champion vs challenger** on most recent holdout (last 48h)
5. **Swaps if challenger wins** by > 1 AUC point on holdout

```python
class OnlineLearner:
    def __init__(self):
        self.champion_model = None
        self.champion_auc = 0.0
        self.retrain_interval_hours = 24
        self.min_new_samples = 20  # Don't retrain on tiny batches

    def should_retrain(self, new_samples: int, hours_since_last: float) -> bool:
        return (
            hours_since_last >= self.retrain_interval_hours
            and new_samples >= self.min_new_samples
        )

    def champion_challenger(
        self,
        challenger_model,
        X_holdout,
        y_holdout
    ) -> bool:
        """Returns True if challenger should replace champion."""
        from sklearn.metrics import roc_auc_score

        champion_auc = roc_auc_score(
            y_holdout,
            self.champion_model.predict_proba(X_holdout)[:, 1]
        )
        challenger_auc = roc_auc_score(
            y_holdout,
            challenger_model.predict_proba(X_holdout)[:, 1]
        )

        # Challenger must beat champion by margin to prevent flip-flopping
        if challenger_auc > champion_auc + 0.01:
            self.champion_model = challenger_model
            self.champion_auc = challenger_auc
            return True
        return False
```

### Why NOT True Online Learning (SGD/incremental)

- XGBoost doesn't support true incremental learning well
- Full retrain on 55K rows takes <1 minute — fast enough for hourly
- Full retrain avoids catastrophic forgetting and model drift from bad batches
- Champion-challenger pattern adds safety: bad retrains get rejected

---

## 7. Regime Detection (Know When NOT to Bet)

V5 includes a simple regime filter that overrides predictions:

```python
def get_regime(features: dict) -> str:
    """Classify current market regime."""
    adx = features['adx_14']
    atr_ratio = features['atr_ratio']

    if atr_ratio > 0.03:  # >3% ATR/price = extreme volatility
        return 'chaotic'  # DON'T TRADE
    elif adx > 25:
        return 'trending'  # Trade with trend
    else:
        return 'ranging'   # Trade mean-reversion or skip
```

| Regime | ADX | ATR Ratio | Action |
|--------|-----|-----------|--------|
| Trending | > 25 | < 3% | Trade normally |
| Ranging | < 25 | < 3% | Trade with reduced size |
| Chaotic | Any | > 3% | **No trades** — sit on hands |

The "chaotic" gate addresses the user's concern about 4h being "skewed by random events." Even at 1h, flash crashes and news bombs happen. When volatility spikes, the model's training distribution no longer applies.

---

## 8. Schema Design (v5 Supabase Schema)

```sql
-- New schema for V5
CREATE SCHEMA IF NOT EXISTS v5;

-- 1. OHLCV data (both historical backfill and live)
CREATE TABLE v5.ohlcv_1h (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    bucket_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    source TEXT DEFAULT 'binance',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, bucket_time)
);

-- 2. Computed features (audit trail)
CREATE TABLE v5.features_1h (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    bucket_time TIMESTAMPTZ NOT NULL,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    features JSONB NOT NULL,  -- All 12 features as key-value
    feature_version TEXT DEFAULT 'v1',
    UNIQUE(symbol, bucket_time, feature_version)
);

-- 3. Model registry
CREATE TABLE v5.models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    trained_at TIMESTAMPTZ DEFAULT NOW(),
    train_start TIMESTAMPTZ,
    train_end TIMESTAMPTZ,
    train_samples INT,
    val_auc DOUBLE PRECISION,
    val_accuracy DOUBLE PRECISION,
    hyperparameters JSONB,
    feature_columns JSONB,
    model_bytes BYTEA,
    is_deployed BOOLEAN DEFAULT FALSE,
    deployed_at TIMESTAMPTZ,
    notes TEXT,
    UNIQUE(model_name, version)
);

-- 4. Predictions
CREATE TABLE v5.predictions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    bucket_time TIMESTAMPTZ NOT NULL,       -- Which 1h candle this predicts
    predicted_at TIMESTAMPTZ DEFAULT NOW(),  -- When prediction was made
    model_id UUID REFERENCES v5.models(id),
    direction TEXT NOT NULL,                 -- 'UP' or 'DOWN'
    probability DOUBLE PRECISION NOT NULL,  -- Calibrated probability
    confidence_tier TEXT NOT NULL,           -- 'SKIP', 'LOW', 'MEDIUM', 'HIGH'
    regime TEXT,                             -- 'trending', 'ranging', 'chaotic'
    features_snapshot JSONB,                -- Feature values at prediction time
    -- Outcome (filled after candle closes)
    actual_direction TEXT,
    actual_pct_change DOUBLE PRECISION,
    is_correct BOOLEAN,
    scored_at TIMESTAMPTZ,
    -- Execution
    trade_executed BOOLEAN DEFAULT FALSE,
    trade_details JSONB,
    UNIQUE(symbol, bucket_time)
);

-- 5. Performance log (rolling metrics)
CREATE TABLE v5.performance_log (
    id BIGSERIAL PRIMARY KEY,
    logged_at TIMESTAMPTZ DEFAULT NOW(),
    symbol TEXT NOT NULL,
    window_hours INT NOT NULL,              -- e.g. 24, 72, 168 (1w)
    total_predictions INT,
    accuracy DOUBLE PRECISION,
    high_conf_accuracy DOUBLE PRECISION,
    avg_confidence DOUBLE PRECISION,
    calibration_error DOUBLE PRECISION,
    sharpe_ratio DOUBLE PRECISION,
    model_id UUID REFERENCES v5.models(id)
);

-- 6. Retraining log
CREATE TABLE v5.retrain_log (
    id BIGSERIAL PRIMARY KEY,
    retrained_at TIMESTAMPTZ DEFAULT NOW(),
    old_model_id UUID REFERENCES v5.models(id),
    new_model_id UUID REFERENCES v5.models(id),
    holdout_auc_old DOUBLE PRECISION,
    holdout_auc_new DOUBLE PRECISION,
    was_swapped BOOLEAN,
    reason TEXT
);

-- Indexes
CREATE INDEX idx_v5_ohlcv_lookup ON v5.ohlcv_1h(symbol, bucket_time DESC);
CREATE INDEX idx_v5_features_lookup ON v5.features_1h(symbol, bucket_time DESC);
CREATE INDEX idx_v5_predictions_lookup ON v5.predictions(symbol, bucket_time DESC);
CREATE INDEX idx_v5_predictions_unscored ON v5.predictions(scored_at) WHERE scored_at IS NULL;
CREATE INDEX idx_v5_models_deployed ON v5.models(is_deployed) WHERE is_deployed = TRUE;
```

---

## 9. Implementation Phases

### Phase 0: Signal Validation (DO THIS FIRST)

**Goal**: Before building any infrastructure, prove that a learnable signal exists in the 1h data.

```
1. Pull training.spot_1h data (55K rows per pair)
2. Compute features using compute_features()
3. Create labels: close[t+1] > close[t] → UP (1), else DOWN (0)
4. Run walk-forward CV (6-month train, 1-month val, 48h embargo)
5. Report: AUC, accuracy per fold, accuracy per pair
6. SUCCESS CRITERIA: Average val AUC > 0.55 AND val accuracy > 54% consistently
7. If fails → STOP. The signal doesn't exist at this timeframe.
```

This is the most important phase. If 12 features on 55K rows of clean 1h data can't beat 54% in walk-forward CV with proper embargo, then adding more complexity won't help.

### Phase 1: Schema + Data Pipeline

1. Create v5 schema in Supabase
2. Backfill v5.ohlcv_1h from training.spot_1h (historical)
3. Set up live OHLCV ingestion (Binance API → v5.ohlcv_1h)
4. Implement compute_features() in Python module
5. Backfill v5.features_1h from historical OHLCV

### Phase 2: Training Pipeline

1. Build walk-forward CV with embargo
2. Train initial XGBoost model on full historical data
3. Calibrate with Platt scaling on validation set
4. Store model in v5.models
5. Run pre-deployment checks (AUC > 0.55, calibration error < 0.1)

### Phase 3: Inference Loop

1. Hourly cron: fetch candle → compute features → predict → log
2. Regime detection gating
3. Confidence tier filtering
4. Score predictions after candle closes
5. Performance logging (24h, 72h, 168h rolling windows)

### Phase 4: Execution (Polymarket CLOB)

1. Integrate py-clob-client for Polymarket trading
2. Position sizing based on confidence tier
3. Order management (limit orders, cancellation, fills)
4. P&L tracking

### Phase 5: Continuous Retraining

1. Champion-challenger loop (every 24h)
2. Expanding window retraining
3. Model swap with rollback capability
4. Alert on performance degradation (accuracy < 52% over 72h)

---

## 10. Success Criteria

| Metric | Minimum | Target | Current Best (V2) |
|--------|---------|--------|-------------------|
| Val AUC (walk-forward) | > 0.55 | > 0.60 | N/A (rule-based) |
| Live Accuracy | > 54% | > 58% | 57.98% |
| HIGH Conf Accuracy | > 60% | > 65% | ~63% |
| Calibration Error | < 0.15 | < 0.08 | 0.22-0.36 (V4) |
| Sharpe Ratio (24h rolling) | > 0.0 | > 0.5 | -0.409 to +0.847 (V4) |
| Backtest-to-Live Gap | < 5pp | < 3pp | -7pp (V2), -30pp (V3) |

### Kill Switch

If after 1 week of live predictions:
- Accuracy < 52% overall → Pause and investigate
- HIGH confidence accuracy < 55% → Reduce to LOG_ONLY mode
- Sharpe < -0.5 → Stop all trading

---

## 11. What's Different About V5

| Dimension | V3/V4 | V5 |
|-----------|-------|-----|
| Features | 53-272, many computed differently in training vs live | 12, one function for both |
| Validation | Walk-forward but with lookback leakage | Walk-forward with 48h embargo |
| Model | XGBoost (V3) / Ensemble (V4) | Single XGBoost, calibrated |
| Confidence | Raw model probability | Platt-scaled, 4 tiers |
| Regime | None | ADX + ATR gating |
| Retraining | Static (train once, deploy forever) | Continuous champion-challenger |
| Position sizing | Flat (all or nothing) | Tiered by confidence |
| Execution | Manual or fragile | Automated via py-clob-client |
| When to NOT bet | Always bet | SKIP tier + chaotic regime = sit out |
| Signal validation | None (assumed signal exists) | Phase 0 proves signal first |

---

**Document Created**: February 6, 2026
**Author**: V5 Architecture Team
**Status**: Ready for Phase 0 — Signal Validation


# Why V5 Will Be Different

## The Core Problem V1-V4 All Shared

Every prior model treated crypto price prediction as a classification problem with static features. Feed indicators into XGBoost, get a probability, bet on it. They all failed for the same root cause: **the market changes regimes faster than the model can adapt, and raw indicator snapshots don't capture what's actually happening.**

V1 got 53% accuracy but couldn't beat the vig. V2's first-minute model hit 57.98% on a clever trick but wasn't generalizable. V3 proved which features matter but couldn't translate importance into live edge. V4 had one bright spot — SOL 1h at 60.9% with +0.665 Sharpe — but couldn't replicate it across pairs or timeframes.

The lesson isn't that prediction is impossible. The lesson is that **what** you predict with matters more than **how** you predict.

---

## What V5 Does Differently

### 1. Indicators, Not Raw OHLCV

V1-V4 computed features from raw candle data — returns, volatility ratios, moving average crossovers. This means the model had to learn what RSI *is* from price changes. That's asking XGBoost to reinvent technical analysis from scratch with 55K rows.

V5 pulls from a pre-computed indicators schema with 30+ indicators across 6 timeframes (1m, 5m, 15m, 30m, 1h, 2h). The model gets RSI directly, not `close / close.shift(14)`. It gets MACD histogram, not `ema12 - ema26 - signal9`. This is a fundamental input quality upgrade — the features start meaningful instead of hoping the model discovers meaning.

### 2. Multi-Timeframe Signals

V1-V4 operated on a single timeframe per model. A 1h model saw 1h data. Period.

Markets don't work that way. A 5m chart showing oversold stochastic (16) while the 1h shows overbought (82) is telling you something neither chart says alone. We proved this in live scoring — the multi-timeframe scorer caught divergences that single-timeframe analysis missed entirely.

V5 ingests signals across timeframes and lets the model learn cross-timeframe relationships. When 5m momentum flips positive but 1h volume is still distributing, that's a pattern. No single-timeframe model can see it.

### 3. Synthetic Indicators — The Missing Layer

This is the real unlock.

Raw indicators are gauges. RSI = 65. Stochastic = 77. CVD = -1,405. Static numbers. What they don't tell you:

- **Is RSI rising or falling?** V3 proved `rsi_slope_3` was the single most important feature at 10-12% importance. A slope is a synthetic — it's computed from the indicator, not from price.

- **Is selling pressure accelerating or decelerating?** CVD at -1,405 could mean aggressive selling or exhausted selling. Only `cvd_acceleration` (the second derivative) distinguishes them. We proved this matters in live scoring — BTC showed decelerating CVD on 5m before ripping $700 upward. The raw CVD number still said "bearish." The acceleration would have said "sellers are done."

- **Do independent volume signals agree?** CMF and CVD measure volume flow differently. When both are negative, that's high-conviction distribution. When they diverge, the signal is noise. A `cmf_cvd_confluence` binary flag captures this.

- **Is the trend strong enough to trust?** ADX > 25 with +DI leading -DI by 10+ means the trend is real. ADX < 20 means MACD crossovers are whipsaws. Gating trend signals on ADX strength is a synthetic that filters garbage.

These aren't theoretical. V3's feature importance rankings already proved that derived features (slopes, percentile ranks, boolean flags) outperform raw indicator values. V5 builds on that systematically.

### 4. Regime-Aware Dynamic Weighting

V1-V4 used one model for all market conditions. Same features, same weights, whether the market was trending, ranging, or chaotic.

V5 detects the regime first (using ADX + ATR ratio) then adjusts which signals to trust:

- **TRENDING** (ADX > 25): Trust MACD, momentum, DI crossovers. Discount mean-reversion signals.
- **RANGING** (ADX < 25): Trust oscillator extremes, BB position, mean reversion. Discount trend-following signals.
- **CHAOTIC** (ATR/price > 3%): Trust volume divergence and BB extremes only. Everything else is noise.

This isn't a separate model per regime — it's dynamic weight adjustment within one scorer. The regime detection runs first, then the component weights shift. Simple, no extra training data needed.

### 5. Walk-Forward Training with Kill Gates

V1-V4 used standard train/test splits or basic cross-validation. This allowed subtle lookahead contamination and didn't test adaptation.

V5 uses expanding-window walk-forward validation with hard kill gates:

- **Signal validation gate**: AUC ≥ 0.54, accuracy ≥ 0.53, train-val gap < 5%. If features don't pass this on raw signal alone, the model doesn't deploy. This already caught two rounds of bad features — working as designed.
- **48-hour embargo**: No data from the 48 hours before each validation fold enters training. Eliminates short-term autocorrelation leakage.
- **Live performance monitoring**: If deployed model accuracy drops below 52% over a rolling window, it auto-retrains or shuts down.

### 6. The DOWN Bias

Every version confirmed it: DOWN predictions outperform UP by 3-6 percentage points across all pairs and timeframes. This isn't noise — it's structural. Crypto markets have positive drift (they go up over time) but short-term mean reversion (overbought conditions resolve downward more reliably than oversold conditions resolve upward).

V5 bakes in a -0.03 constant bias. It's small enough to not override strong bullish signals but large enough to tip coin-flip situations toward the statistically correct side.

---

## What We Learned From Live Scoring

Before V5 even trains a model, we built a systematic scorer and tested it in real-time. Results:

**What worked:**
- Volume divergence (CVD direction vs price direction) was the single most reliable signal
- Multi-timeframe analysis caught signals that single-timeframe missed
- Regime detection correctly identified when to trust which signals
- The DOWN bias correctly tipped marginal calls

**What failed and why:**
- BTC called BELOW when it ripped +$700 in 9 minutes. Root cause: the scorer saw negative CVD (bearish) but couldn't see that CVD was *decelerating* (sellers exhausting). A `cvd_slope` or `cvd_acceleration` synthetic would have caught this. Static snapshots missed the trajectory.
- Multiple BELOW calls in a row — the scorer has a structural bearish lean from volume divergence + DOWN bias that may be too aggressive when short-term momentum is flipping

**What this means for V5:**
The live scoring exercise validated the *architecture* (multi-timeframe, regime-aware, weighted components) while exposing the specific gap (no rate-of-change features, no confluence detection). V5's training pipeline builds exactly these synthetic features, which is why we expect it to outperform the rule-based scorer.

---

## Why This Time Is Different (Honestly)

Every failed model version could have written a doc like this. "This time we fixed X." So why believe V5?

Because V5 is the first version built *backward from failure analysis* rather than forward from assumptions:

- V1 assumed raw OHLCV features would work → V5 uses pre-computed indicators
- V2 assumed a clever trick (first-minute direction) would generalize → V5 uses systematic feature engineering validated by importance rankings
- V3 proved which features matter but didn't act on it → V5's feature set is directly derived from V3's importance rankings
- V4 showed one pair/timeframe combo could work (SOL 1h, 60.9%) → V5's architecture is designed to find and exploit these pockets rather than forcing all pairs into one model
- All versions missed regime detection → V5 gates every signal on regime
- All versions used static features → V5 introduces synthetic rate-of-change and confluence features
- All versions had no kill switch → V5 has hard gates at signal validation and live performance

The signal validation gate has already stopped two bad models from deploying. That alone is new — V1-V4 would have shipped those and lost money.

V5 isn't guaranteed to work. But it's the first version that knows *why* the others failed and is specifically engineered to address each failure mode.
