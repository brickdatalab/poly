# WaveTrend Oscillator (WT_LB) - Technical Analysis & Mathematical Specification

## Executive Summary

The WaveTrend indicator is a **volatility-normalized momentum oscillator** that measures price deviation from a smoothed average, scaled by market volatility. It produces two oscillating lines (WT1 and WT2) that generate signals via crossovers and threshold breaches.

---

## 1. Configurable Parameters

| Parameter | Variable | Default | Range | Purpose |
|-----------|----------|---------|-------|---------|
| Channel Length | `n1` | 10 | 5-20 | Controls price smoothing responsiveness |
| Average Length | `n2` | 21 | 10-50 | Controls signal smoothing/lag |
| Over Bought Level 1 | `obLevel1` | 60 | 50-80 | Primary resistance threshold |
| Over Bought Level 2 | `obLevel2` | 53 | 40-70 | Early warning resistance |
| Over Sold Level 1 | `osLevel1` | -60 | -80 to -50 | Primary support threshold |
| Over Sold Level 2 | `osLevel2` | -53 | -70 to -40 | Early warning support |

From the image header, current values shown: `10 21 60 53 -60 -53` (standard configuration)

---

## 2. Mathematical Specification

### 2.1 Core Algorithm (Step-by-Step)

```
INPUTS:
  H[t] = High price at bar t
  L[t] = Low price at bar t  
  C[t] = Close price at bar t
  n1 = Channel Length (default: 10)
  n2 = Average Length (default: 21)

STEP 1: Calculate Typical Price
  AP[t] = (H[t] + L[t] + C[t]) / 3

STEP 2: Calculate Exponential Smoothed Average of Price
  ESA[t] = EMA(AP, n1)
  
  Where EMA uses smoothing factor:
  α₁ = 2 / (n1 + 1)
  
  Recursive formula:
  ESA[t] = α₁ × AP[t] + (1 - α₁) × ESA[t-1]

STEP 3: Calculate Mean Absolute Deviation (Volatility Measure)
  D[t] = EMA(|AP - ESA|, n1)
  D[t] = α₁ × |AP[t] - ESA[t]| + (1 - α₁) × D[t-1]

STEP 4: Calculate Channel Index (Normalized Deviation)
  CI[t] = (AP[t] - ESA[t]) / (0.015 × D[t])

STEP 5: Calculate WaveTrend Line 1 (Smoothed Channel Index)
  WT1[t] = EMA(CI, n2)
  
  Where:
  α₂ = 2 / (n2 + 1)
  WT1[t] = α₂ × CI[t] + (1 - α₂) × WT1[t-1]

STEP 6: Calculate WaveTrend Line 2 (Signal Line)
  WT2[t] = SMA(WT1, 4)
  WT2[t] = (WT1[t] + WT1[t-1] + WT1[t-2] + WT1[t-3]) / 4

OUTPUTS:
  WT1[t] = Primary oscillator value (green line)
  WT2[t] = Signal line (red dotted line)
  HISTOGRAM[t] = WT1[t] - WT2[t] (blue shaded area)
```

### 2.2 Mathematical Constants

| Constant | Value | Derivation |
|----------|-------|------------|
| α₁ (n1=10) | 0.1818 | 2/(10+1) |
| α₁ (n1=9) | 0.2000 | 2/(9+1) |
| α₂ (n2=21) | 0.0909 | 2/(21+1) |
| α₂ (n2=12) | 0.1538 | 2/(12+1) |
| Normalization | 0.015 | Scales output to approximately ±100 range |

### 2.3 The 0.015 Normalization Constant

This constant is derived from the Commodity Channel Index (CCI) formula and ensures:
- Mean reversion around 0
- Typical oscillation range: ±60 (normal), ±100 (extreme)
- Statistical basis: ~66.67× amplification of the normalized deviation

---

## 3. Effective Lookback Analysis

### 3.1 EMA Decay Characteristics

For an EMA with period `n`, the weight contribution decays as:

```
Weight at lag k = α × (1-α)^k

Cumulative weight after k bars = 1 - (1-α)^(k+1)
```

**Key decay milestones for standard settings:**

| Bars Back | Weight Remaining (n1=10) | Weight Remaining (n2=21) |
|-----------|-------------------------|-------------------------|
| 5 | 59.3% | 77.4% |
| 10 | 35.1% | 59.9% |
| 21 | 13.5% | 35.5% |
| 35 | 4.8% | 19.4% |

### 3.2 Total Effective Lookback

The cascaded processing creates compound latency:

```
Standard (10, 21):
  Total Effective Lookback ≈ n1 + n2 + 4 = 35 bars
  86.5% weight coverage ≈ 2×(n1 + n2) = 62 bars

Aggressive (9, 12):
  Total Effective Lookback ≈ 9 + 12 + 4 = 25 bars
  86.5% weight coverage ≈ 2×(9 + 12) = 42 bars
```

---

## 4. Timeframe Calculations for 15-Minute Prediction Window

### 4.1 Settings Matrix

| Chart TF | Config | Effective Lookback | Prediction Horizon | Recommendation |
|----------|--------|-------------------|-------------------|----------------|
| 1-min | Standard (10,21) | 35 min | 15 candles | ⚠️ Too lagging |
| 1-min | Aggressive (9,12) | 25 min | 15 candles | ✅ **OPTIMAL** |
| 5-min | Standard (10,21) | 175 min | 3 candles | ❌ Too slow |
| 5-min | Aggressive (9,12) | 125 min | 3 candles | ✅ Viable |
| 15-min | Standard (10,21) | 525 min | 1 candle | ❌ Not suitable |
| 15-min | Aggressive (9,12) | 375 min | 1 candle | ⚠️ Marginal |

### 4.2 Recommended Configuration for 15-Minute Predictions

```
PRIMARY RECOMMENDATION:
  Chart Timeframe: 1-minute
  Channel Length (n1): 9
  Average Length (n2): 12
  
  Rationale: 
  - 25-bar lookback × 1-min = 25 minutes of data
  - Provides 15 forward candles for prediction horizon
  - Faster α values (0.20, 0.154) capture recent momentum shifts
```

---

## 5. Signal Generation Logic

### 5.1 Signal Definitions

```python
# BULLISH SIGNAL (Long/UP prediction)
def bullish_signal(wt1, wt2, wt1_prev, wt2_prev, ob_level):
    crossover = (wt1_prev <= wt2_prev) AND (wt1 > wt2)
    not_overbought = wt1 < ob_level
    return crossover AND not_overbought

# BEARISH SIGNAL (Short/DOWN prediction)  
def bearish_signal(wt1, wt2, wt1_prev, wt2_prev, os_level):
    crossunder = (wt1_prev >= wt2_prev) AND (wt1 < wt2)
    not_oversold = wt1 > os_level
    return crossunder AND not_oversold

# SIGNAL STRENGTH (Confidence modifier)
def signal_strength(wt1, histogram):
    if abs(wt1) > 53:
        return "STRONG"  # In extreme zone
    elif abs(histogram) > 10:
        return "MODERATE"  # Clear divergence
    else:
        return "WEAK"  # Neutral zone
```

### 5.2 Signal Interpretation Matrix

| WT1 Zone | WT1 vs WT2 | Histogram | Signal | Confidence |
|----------|------------|-----------|--------|------------|
| < -60 | Crossing Above | Turning Positive | **STRONG BUY** | High |
| -53 to -60 | Crossing Above | Turning Positive | **BUY** | Medium-High |
| -53 to +53 | Crossing Above | Positive | **WEAK BUY** | Low |
| +53 to +60 | Crossing Below | Turning Negative | **SELL** | Medium-High |
| > +60 | Crossing Below | Turning Negative | **STRONG SELL** | High |

---

## 6. Strengths & Limitations

### 6.1 Positive Attributes

| Attribute | Explanation | Mathematical Basis |
|-----------|-------------|-------------------|
| **Volatility Normalization** | Self-scales to market conditions | Division by D[t] (mean deviation) |
| **Non-Repainting** | Uses confirmed close prices only | hlc3 calculated on bar close |
| **Noise Reduction** | Double EMA cascade filters HF noise | Low-pass filter cascade |
| **Clear Thresholds** | Binary decision boundaries | Fixed OB/OS levels |
| **Mean Reverting** | Oscillates around zero | Normalization by 0.015 |

### 6.2 Negative Attributes / Failure Modes

| Limitation | Condition | Mitigation |
|------------|-----------|------------|
| **Lagging** | Fast price moves | Use aggressive settings (9,12) |
| **Extended Extremes** | Strong trends | Don't fade first touch of OB/OS |
| **False Crossovers** | Choppy/ranging markets | Require confirmation (histogram flip) |
| **Fixed Thresholds** | Different volatility regimes | Consider adaptive thresholds |
| **No Price Targets** | Binary direction only | Combine with support/resistance |

---

## 7. Implementation for Prediction Model

### 7.1 Feature Extraction

```python
def extract_wavetrend_features(ohlc_data, n1=9, n2=12):
    """
    Extract features for ML/prediction model
    
    Returns dict with:
    - wt1: Current WT1 value
    - wt2: Current WT2 value  
    - histogram: WT1 - WT2
    - wt1_slope: Rate of change of WT1
    - zone: Current zone classification
    - crossover_bars_ago: Bars since last crossover
    - divergence: Price vs WT1 divergence
    """
    
    features = {}
    
    # Core values
    features['wt1'] = wt1[-1]
    features['wt2'] = wt2[-1]
    features['histogram'] = wt1[-1] - wt2[-1]
    
    # Momentum
    features['wt1_slope'] = wt1[-1] - wt1[-3]  # 3-bar slope
    features['histogram_slope'] = features['histogram'] - (wt1[-3] - wt2[-3])
    
    # Zone classification
    if features['wt1'] > 60:
        features['zone'] = 2  # Extreme overbought
    elif features['wt1'] > 53:
        features['zone'] = 1  # Overbought
    elif features['wt1'] < -60:
        features['zone'] = -2  # Extreme oversold
    elif features['wt1'] < -53:
        features['zone'] = -1  # Oversold
    else:
        features['zone'] = 0  # Neutral
    
    # Signal state
    features['bullish_cross'] = (wt1[-2] <= wt2[-2]) and (wt1[-1] > wt2[-1])
    features['bearish_cross'] = (wt1[-2] >= wt2[-2]) and (wt1[-1] < wt2[-1])
    
    return features
```

### 7.2 Directional Probability Estimation

```python
def estimate_15min_direction_probability(features):
    """
    Convert WaveTrend features to directional probability
    
    Returns: float between 0 (bearish) and 1 (bullish)
    """
    
    base_prob = 0.5  # Neutral starting point
    
    # Zone adjustment (-0.15 to +0.15)
    zone_adj = features['zone'] * -0.075  # Contrarian: extreme zones predict reversal
    
    # Crossover adjustment (-0.20 to +0.20)
    if features['bullish_cross'] and features['zone'] <= 0:
        cross_adj = 0.20
    elif features['bearish_cross'] and features['zone'] >= 0:
        cross_adj = -0.20
    else:
        cross_adj = 0
    
    # Momentum adjustment (-0.10 to +0.10)
    momentum_adj = np.clip(features['histogram_slope'] / 20, -0.10, 0.10)
    
    # Combine
    probability = base_prob + zone_adj + cross_adj + momentum_adj
    
    return np.clip(probability, 0.05, 0.95)
```

---

## 8. Visual Reference (From Chart Image)

Current readings visible in the header: `62.5362` (WT1), `66.3305` (WT2), `-3.7943` (Histogram)

**Interpretation:**
- Both lines in overbought zone (>60)
- WT1 < WT2 → Bearish momentum
- Negative histogram → Downward pressure
- **15-min outlook: BEARISH** (expect pullback toward neutral zone)

---

## 9. Summary Decision Framework

```
FOR 15-MINUTE PREDICTION WINDOW:

Chart: 1-minute candles
Settings: Channel=9, Average=12, OB=60/53, OS=-60/-53

BULLISH PREDICTION when:
  ✓ WT1 crosses above WT2
  ✓ Both lines below +53 (preferably below 0)
  ✓ Histogram turning positive
  ✓ WT1 slope positive

BEARISH PREDICTION when:
  ✓ WT1 crosses below WT2
  ✓ Both lines above -53 (preferably above 0)
  ✓ Histogram turning negative
  ✓ WT1 slope negative

NEUTRAL/NO TRADE when:
  ✗ No crossover in last 3 bars
  ✗ Histogram near zero (|hist| < 3)
  ✗ WT1 in middle zone (-30 to +30) without clear direction
```