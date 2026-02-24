# Stochastic RSI Multi-Timeframe Indicator Analysis

## Executive Summary

This indicator computes a **Smoothed Stochastic RSI** and displays it across five predefined timeframes (15m, 30m, 1h, 4h, 12h) in a table overlay. It is **not a predictive indicator**—it's a momentum oscillator that provides a multi-timeframe view of overbought/oversold conditions. For a 15-minute prediction window, this serves as a feature input rather than a direct price forecaster.

---

## 1. Mathematical Decomposition

### 1.1 Core Calculation Pipeline

The indicator performs three sequential transformations:

```
Close Price → RSI(14) → StochRSI(14) → SMA(3) → Output
```

#### Step 1: Relative Strength Index (RSI)

$$RSI_t = 100 - \frac{100}{1 + RS_t}$$

Where:
$$RS_t = \frac{EMA_{gain}(n)}{EMA_{loss}(n)}$$

- $n$ = `lengthRSI` = 14 (default)
- Uses Wilder's smoothing method (exponential moving average with α = 1/n)
- **Output range**: [0, 100]

#### Step 2: Stochastic Transformation of RSI

The code applies the stochastic formula to the RSI series:

```pinescript
stochRSI = ta.stoch(rsi_curr, rsi_curr, rsi_curr, lengthRSI)
```

This is mathematically equivalent to:

$$StochRSI_t = 100 \times \frac{RSI_t - \min(RSI_{t-n+1:t})}{\max(RSI_{t-n+1:t}) - \min(RSI_{t-n+1:t})}$$

Where:
- $n$ = `lengthRSI` = 14
- **Output range**: [0, 100]
- Measures where RSI sits within its own 14-period range

#### Step 3: Smoothing (Simple Moving Average)

$$SmoothedStochRSI_t = \frac{1}{m} \sum_{i=0}^{m-1} StochRSI_{t-i}$$

Where:
- $m$ = `lengthMovingAverage` = 3 (default)
- **Output range**: [0, 100]

---

## 2. Effective Lookback Analysis

### 2.1 Data Dependency Chain

| Component | Bars Required | Cumulative Bars |
|-----------|---------------|-----------------|
| RSI(14) | 14 | 14 |
| StochRSI(14) | 14 | 14* |
| SMA(3) | 3 | 16 |

*Note: StochRSI operates on RSI values, so bars overlap. The true minimum is ~16 bars for a stable reading.

### 2.2 Time-Based Lookback per Timeframe

For each timeframe with default settings (RSI=14, SMA=3):

| Timeframe | Bars Needed | Absolute Time Lookback |
|-----------|-------------|------------------------|
| 15 min | 16 | 4 hours |
| 30 min | 16 | 8 hours |
| 1 hour | 16 | 16 hours |
| 4 hour | 16 | 2.67 days |
| 12 hour | 16 | 8 days |

**Critical insight**: The higher timeframe values represent momentum state over substantially longer historical windows, creating a hierarchical view of market conditions.

---

## 3. Multi-Timeframe Architecture

### 3.1 Request Security Calls

```pinescript
T15_RSI_TickerR = request.security(syminfo.tickerid, timeframe.period, stochRSI_smoth)
T15_RSI_Ticker  = request.security(syminfo.tickerid, timeframe.period, stochRSI_smoth[barstate.isrealtime ? 1:0])
T30_RSI_Ticker  = request.security(syminfo.tickerid, "30", stochRSI_smoth[barstate.isrealtime ? 1:0])
T60_RSI_Ticker  = request.security(syminfo.tickerid, "60", stochRSI_smoth[barstate.isrealtime ? 1:0])
T4h_RSI_Ticker  = request.security(syminfo.tickerid, "240", stochRSI_smoth[barstate.isrealtime ? 1:0])
T12h_RSI_Ticker = request.security(syminfo.tickerid, "720", stochRSI_smoth[barstate.isrealtime ? 1:0])
```

### 3.2 Repaint Prevention Logic

The expression `stochRSI_smoth[barstate.isrealtime ? 1:0]`:

| Condition | Offset | Meaning |
|-----------|--------|---------|
| Live/Realtime | [1] | Uses **previous closed bar** |
| Historical | [0] | Uses **current bar** |

**Why this matters**: 
- Prevents lookahead bias in backtesting
- `T15_RSI_TickerR` (without offset) DOES repaint and shows real-time updating values
- All other values are "confirmed" (non-repainting)

---

## 4. Configurable Parameters

| Parameter | Variable | Default | Valid Range | Effect |
|-----------|----------|---------|-------------|--------|
| RSI Length | `lengthRSI` | 14 | 2-200 | Controls sensitivity of RSI and StochRSI lookback |
| Smoothing Length | `lengthMovingAverage` | 3 | 1-50 | Higher = smoother, more lag; 1 = raw signal |

### 4.1 Parameter Trade-offs

**RSI Length (14)**:
- Lower values → More responsive, more noise, more false signals
- Higher values → Smoother, more lag, fewer but more reliable signals

**Smoothing Length (3)**:
- `1` = No smoothing, maximum sensitivity (described as "sharper signal, higher false alarm risk")
- `3` = Balanced (default)
- Higher = More lag, filtered noise

---

## 5. Signal Interpretation Framework

### 5.1 Threshold Zones

| Zone | StochRSI Range | Interpretation |
|------|----------------|----------------|
| Overbought | > 80 | Momentum exhaustion high, potential reversal down |
| Neutral | 20-80 | No clear directional bias |
| Oversold | < 20 | Momentum exhaustion low, potential reversal up |

### 5.2 Multi-Timeframe Confluence Logic

For prediction purposes, the MTF data creates a hierarchical momentum picture:

```
Signal Strength = f(alignment across timeframes)

Strong Bullish: All TFs < 20 (oversold) → Higher probability upward reversal
Strong Bearish: All TFs > 80 (overbought) → Higher probability downward reversal
Divergent: Mixed signals → Low confidence / consolidation
```

**Mathematical representation for ML feature engineering**:

$$Confluence_{bullish} = \sum_{tf \in TFs} \mathbb{1}(StochRSI_{tf} < 20)$$
$$Confluence_{bearish} = \sum_{tf \in TFs} \mathbb{1}(StochRSI_{tf} > 80)$$

---

## 6. Configuration for 15-Minute Prediction Window

### 6.1 Required Settings

| Setting | Value | Justification |
|---------|-------|---------------|
| **Chart Timeframe** | 15 minutes | **MANDATORY** - Hardcoded MTF strings assume 15m base |
| RSI Length | 14 | Standard; 16 bars × 15 min = 4-hour lookback |
| Smoothing | 3 | Balanced signal quality |

### 6.2 Why 15-Minute Chart is Non-Negotiable

The indicator hardcodes timeframe strings:
```pinescript
"30"   // 30 minutes
"60"   // 60 minutes  
"240"  // 4 hours
"720"  // 12 hours
```

If you use a different base timeframe (e.g., 5 minutes):
- The `timeframe.period` for T15 would actually be 5 minutes, not 15
- The MTF hierarchy breaks down
- You'd be comparing 5m vs 30m vs 60m vs 240m vs 720m — not the intended ratios

---

## 7. Feature Engineering for Prediction Models

### 7.1 Extractable Features (Per Bar)

| Feature | Description | Range |
|---------|-------------|-------|
| `stoch_rsi_15m` | Current TF smoothed value | [0, 100] |
| `stoch_rsi_30m` | 30-min smoothed value | [0, 100] |
| `stoch_rsi_1h` | 1-hour smoothed value | [0, 100] |
| `stoch_rsi_4h` | 4-hour smoothed value | [0, 100] |
| `stoch_rsi_12h` | 12-hour smoothed value | [0, 100] |

### 7.2 Derived Features for ML

```python
# Momentum gradient across timeframes
momentum_slope = (stoch_rsi_15m - stoch_rsi_12h) / 5  # Normalized slope

# Zone encoding
is_oversold_15m = 1 if stoch_rsi_15m < 20 else 0
is_overbought_15m = 1 if stoch_rsi_15m > 80 else 0

# Confluence score (-5 to +5)
bullish_confluence = sum([1 if v < 30 else 0 for v in all_tf_values])
bearish_confluence = sum([1 if v > 70 else 0 for v in all_tf_values])

# Rate of change (if you have historical values)
stoch_rsi_15m_roc = stoch_rsi_15m - stoch_rsi_15m_prev
```

---

## 8. Strengths and Limitations

### 8.1 Strengths (✓)

| Aspect | Benefit |
|--------|---------|
| **Multi-timeframe view** | Captures momentum context from micro to macro |
| **Bounded output** | [0,100] range normalizes across assets |
| **Repaint prevention** | Proper `[1]` offset on realtime bars |
| **Smoothing option** | Configurable noise filtering |
| **Computationally simple** | Fast calculation, low latency |

### 8.2 Limitations (✗)

| Aspect | Issue |
|--------|-------|
| **Not predictive** | Measures current state, not future price |
| **Lagging indicator** | Smoothing adds delay to signal |
| **Fixed timeframes** | Cannot adjust MTF ratios without code edit |
| **No divergence detection** | Price vs. indicator divergence not computed |
| **Single instrument** | Commented-out BTC/ETH correlation analysis |
| **Chart TF locked** | Must use 15-min chart for correct operation |

---

## 9. Pseudocode Reconstruction

For implementation in another system:

```python
def calculate_smoothed_stoch_rsi(close_prices, rsi_length=14, smooth_length=3):
    """
    Calculate Smoothed Stochastic RSI
    
    Args:
        close_prices: Array of closing prices (oldest to newest)
        rsi_length: Period for RSI and Stochastic calculation
        smooth_length: SMA smoothing period
    
    Returns:
        float: Smoothed StochRSI value [0-100]
    """
    
    # Step 1: Calculate RSI
    rsi_values = []
    for i in range(rsi_length, len(close_prices)):
        gains = []
        losses = []
        for j in range(i - rsi_length + 1, i + 1):
            change = close_prices[j] - close_prices[j-1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))
        
        avg_gain = wilder_smoothing(gains, rsi_length)
        avg_loss = wilder_smoothing(losses, rsi_length)
        
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi = 100 - (100 / (1 + rs))
        rsi_values.append(rsi)
    
    # Step 2: Calculate Stochastic of RSI
    stoch_rsi_values = []
    for i in range(rsi_length - 1, len(rsi_values)):
        window = rsi_values[i - rsi_length + 1:i + 1]
        lowest = min(window)
        highest = max(window)
        
        if highest - lowest == 0:
            stoch_rsi = 50  # Undefined case, use midpoint
        else:
            stoch_rsi = 100 * (rsi_values[i] - lowest) / (highest - lowest)
        
        stoch_rsi_values.append(stoch_rsi)
    
    # Step 3: Apply SMA smoothing
    if len(stoch_rsi_values) >= smooth_length:
        smoothed = sum(stoch_rsi_values[-smooth_length:]) / smooth_length
    else:
        smoothed = stoch_rsi_values[-1] if stoch_rsi_values else 50
    
    return smoothed
```

---

## 10. Recommended Usage for 15-Minute Predictions

### Primary Use Case
Use as a **momentum context feature** in a larger prediction model, not as a standalone signal generator.

### Integration Pattern
```
Prediction Model Inputs:
├── Price features (OHLCV)
├── This indicator's outputs:
│   ├── stoch_rsi_15m (primary signal for 15-min window)
│   ├── stoch_rsi_30m (confirmation, 2x horizon)
│   ├── stoch_rsi_1h (trend context)
│   └── Derived confluence scores
└── Other indicators/features
```

### Decision Thresholds for 15-Minute Window
| Condition | Interpretation | Suggested Weight |
|-----------|---------------|------------------|
| 15m < 20 AND 30m < 30 | Strong oversold, reversal likely | +2 bullish |
| 15m > 80 AND 30m > 70 | Strong overbought, reversal likely | +2 bearish |
| 15m crossing above 20 | Momentum turning bullish | +1 bullish |
| 15m crossing below 80 | Momentum turning bearish | +1 bearish |

---

## Note on Attached Image

The image you provided shows a **WaveTrend Oscillator**, which is a different indicator from the Stochastic RSI code analyzed above. The WaveTrend Oscillator has different parameters (WT_LB 10 21 60 53...) and calculation methodology. If you need analysis of that indicator as well, please provide its PineScript code.