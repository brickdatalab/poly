# Predicta Futures - Mathematical & Logical Framework
## For Supabase Implementation

---

## Table of Contents
1. [Overview](#overview)
2. [Required Data Points](#required-data-points)
3. [Configurable Parameters](#configurable-parameters)
4. [Core Calculations](#core-calculations)
5. [Indicator Computations](#indicator-computations)
6. [Scoring System](#scoring-system)
7. [Confluence System](#confluence-system)
8. [Final Prediction Logic](#final-prediction-logic)
9. [Output Schema](#output-schema)
10. [Implementation Notes](#implementation-notes)

---

## Overview

This system generates directional probability predictions (UP vs DOWN) for a given asset over a forward-looking time window (e.g., 15 minutes). It uses an 8-point confluence system combining trend, momentum, volume, and volatility indicators, weighted into a final probability score.

**Core Concept:** Multiple technical indicators "vote" on direction. The more indicators that agree, the higher the confidence. Each indicator also contributes a weighted score to calculate final UP/DOWN percentages.

---

## Required Data Points

Your Supabase database needs OHLCV (Open, High, Low, Close, Volume) candle data. For 15-minute Polymarket predictions, you need 15-minute candles.

### Minimum Historical Data Required

| Indicator | Lookback Needed | For 15-min candles |
|-----------|-----------------|-------------------|
| EMA 50 | 50 bars | 12.5 hours |
| ATR Percentile | 100 bars | 25 hours |
| MACD | 26 + 9 = 35 bars | 8.75 hours |
| All others | ≤ 21 bars | 5.25 hours |

**Recommendation:** Store at least **100 candles** of historical data for accurate calculations.

### Candle Data Schema

```sql
CREATE TABLE candles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,  -- '15m', '5m', '1h', etc.
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    UNIQUE(symbol, timestamp, timeframe)
);
```

---

## Configurable Parameters

```javascript
const CONFIG = {
    // Main Settings
    atrLength: 14,           // ATR calculation period
    stFactor: 3.0,           // Supertrend multiplier
    stPeriod: 10,            // Supertrend ATR period
    
    // Confluence Settings
    minConfluence: 5,        // Minimum points needed (out of 8)
    minVolumeRatio: 0.8,     // Minimum volume vs average
    adxThreshold: 25,        // Minimum ADX for trend confirmation
    
    // Fixed Indicator Periods (can be made configurable)
    emaFast: 8,
    emaMid: 21,
    emaSlow: 50,
    rsiPeriod: 14,
    macdFast: 12,
    macdSlow: 26,
    macdSignal: 9,
    stochPeriod: 14,
    stochSmooth: 3,
    adxPeriod: 14,
    volumeSmaPeriod: 20,
    bbPeriod: 20,
    deltaEmaPeriod: 10,
    atrPercentilePeriod: 100,
    
    // Scoring Weights
    weights: {
        trend: 0.23,
        macd: 0.18,
        delta: 0.15,
        rsi: 0.12,
        stoch: 0.12,
        adx: 0.10,
        volume: 0.10
    }
};
```

---

## Core Calculations

### 1. True Range (TR)

```
TR = MAX(
    high - low,
    ABS(high - previous_close),
    ABS(low - previous_close)
)
```

### 2. Average True Range (ATR)

```
ATR(period) = RMA(TR, period)

Where RMA (Running Moving Average / Wilder's Smoothing):
RMA[0] = SMA(values, period)  // First value is simple average
RMA[i] = (RMA[i-1] * (period - 1) + value[i]) / period
```

**Alternative (EMA-based):**
```
ATR = EMA(TR, period)
```

### 3. Exponential Moving Average (EMA)

```
multiplier = 2 / (period + 1)
EMA[0] = SMA(close, period)  // Initialize with SMA
EMA[i] = (close[i] * multiplier) + (EMA[i-1] * (1 - multiplier))
```

### 4. Simple Moving Average (SMA)

```
SMA(values, period) = SUM(values[0..period-1]) / period
```

### 5. Standard Deviation

```
STDEV(values, period) = SQRT(
    SUM((value[i] - SMA(values, period))^2 for i in 0..period-1) / period
)
```

### 6. Percent Rank

```
PERCENTRANK(value, period) = (count of values < current value in last N bars) / period * 100
```

---

## Indicator Computations

### 1. Custom Supertrend

The Supertrend determines the primary trend direction.

```javascript
function calculateSupertrend(candles, factor, period) {
    const atr = calculateATR(candles, period);
    const results = [];
    
    let upperBand = null;
    let lowerBand = null;
    let direction = 1;  // 1 = downtrend, -1 = uptrend
    
    for (let i = 0; i < candles.length; i++) {
        const hl2 = (candles[i].high + candles[i].low) / 2;
        const upperBandRaw = hl2 + (factor * atr[i]);
        const lowerBandRaw = hl2 - (factor * atr[i]);
        
        // Band smoothing logic
        if (i === 0) {
            upperBand = upperBandRaw;
            lowerBand = lowerBandRaw;
        } else {
            const prevClose = candles[i-1].close;
            
            // Lower band: only moves up, never down (in uptrend)
            lowerBand = prevClose > lowerBand 
                ? Math.max(lowerBandRaw, lowerBand) 
                : lowerBandRaw;
            
            // Upper band: only moves down, never up (in downtrend)
            upperBand = prevClose < upperBand 
                ? Math.min(upperBandRaw, upperBand) 
                : upperBandRaw;
        }
        
        // Direction logic
        if (i > 0) {
            const prevDirection = direction;
            if (prevDirection === 1) {  // Was downtrend
                direction = candles[i].close > upperBand ? -1 : 1;
            } else {  // Was uptrend
                direction = candles[i].close < lowerBand ? 1 : -1;
            }
        }
        
        results.push({
            upperBand,
            lowerBand,
            direction,  // -1 = UPTREND, 1 = DOWNTREND
            trendLine: direction === -1 ? lowerBand : upperBand,
            isUptrend: direction === -1,
            isDowntrend: direction === 1
        });
    }
    
    return results;
}
```

**Output:**
- `isUptrend`: Boolean (true when price is above the trend)
- `isDowntrend`: Boolean (true when price is below the trend)
- `trendChanged`: Boolean (direction !== previous direction)

---

### 2. Volume Delta (Leading Indicator)

Estimates buying vs selling pressure within each candle.

```javascript
function calculateVolumeDelta(candles, emaPeriod = 10) {
    const results = [];
    
    for (let i = 0; i < candles.length; i++) {
        const { open, high, low, close, volume } = candles[i];
        const candleRange = high - low;
        
        let buyVolume, sellVolume;
        
        if (candleRange > 0) {
            // Proportional allocation based on close position
            buyVolume = volume * (close - low) / candleRange;
            sellVolume = volume * (high - close) / candleRange;
        } else {
            // Doji candle - split evenly
            buyVolume = volume * 0.5;
            sellVolume = volume * 0.5;
        }
        
        const delta = buyVolume - sellVolume;
        results.push({ buyVolume, sellVolume, delta });
    }
    
    // Calculate EMA of delta
    const deltaValues = results.map(r => r.delta);
    const deltaEma = calculateEMA(deltaValues, emaPeriod);
    
    // Add momentum and direction flags
    for (let i = 0; i < results.length; i++) {
        results[i].deltaEma = deltaEma[i];
        results[i].deltaMomentum = results[i].delta > deltaEma[i];
        results[i].deltaBullish = results[i].delta > 0;
        results[i].deltaBearish = results[i].delta < 0;
    }
    
    return results;
}
```

**Output:**
- `delta`: Raw volume delta value
- `deltaEma`: Smoothed delta
- `deltaMomentum`: Boolean (delta > deltaEma)
- `deltaBullish`: Boolean (delta > 0)
- `deltaBearish`: Boolean (delta < 0)

---

### 3. RSI (Relative Strength Index)

```javascript
function calculateRSI(closes, period = 14) {
    const results = [];
    let avgGain = 0;
    let avgLoss = 0;
    
    for (let i = 0; i < closes.length; i++) {
        if (i === 0) {
            results.push(50);  // Neutral for first value
            continue;
        }
        
        const change = closes[i] - closes[i-1];
        const gain = change > 0 ? change : 0;
        const loss = change < 0 ? Math.abs(change) : 0;
        
        if (i < period) {
            // Accumulate for initial SMA
            avgGain += gain;
            avgLoss += loss;
            
            if (i === period - 1) {
                avgGain /= period;
                avgLoss /= period;
            }
            results.push(50);
        } else {
            // Wilder's smoothing
            avgGain = (avgGain * (period - 1) + gain) / period;
            avgLoss = (avgLoss * (period - 1) + loss) / period;
            
            const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
            const rsi = 100 - (100 / (1 + rs));
            results.push(rsi);
        }
    }
    
    return results;
}
```

**Output:**
- `rsi`: Value 0-100
- `rsiAbove50`: Boolean (rsi > 50)
- `rsiBelow50`: Boolean (rsi < 50)

---

### 4. MACD

```javascript
function calculateMACD(closes, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
    const emaFast = calculateEMA(closes, fastPeriod);
    const emaSlow = calculateEMA(closes, slowPeriod);
    
    const macdLine = emaFast.map((fast, i) => fast - emaSlow[i]);
    const signalLine = calculateEMA(macdLine, signalPeriod);
    const histogram = macdLine.map((macd, i) => macd - signalLine[i]);
    
    return {
        macdLine,
        signalLine,
        histogram
    };
}
```

**Output:**
- `macdLine`: MACD line value
- `signalLine`: Signal line value
- `histogram`: MACD histogram (macdLine - signalLine)

---

### 5. Stochastic Oscillator

```javascript
function calculateStochastic(candles, kPeriod = 14, dPeriod = 3) {
    const stochK = [];
    
    for (let i = 0; i < candles.length; i++) {
        if (i < kPeriod - 1) {
            stochK.push(50);  // Default until enough data
            continue;
        }
        
        // Get highest high and lowest low over K period
        let highestHigh = -Infinity;
        let lowestLow = Infinity;
        
        for (let j = i - kPeriod + 1; j <= i; j++) {
            highestHigh = Math.max(highestHigh, candles[j].high);
            lowestLow = Math.min(lowestLow, candles[j].low);
        }
        
        const range = highestHigh - lowestLow;
        const k = range > 0 
            ? ((candles[i].close - lowestLow) / range) * 100 
            : 50;
        
        stochK.push(k);
    }
    
    // %D is SMA of %K
    const stochD = calculateSMA(stochK, dPeriod);
    
    return { stochK, stochD };
}
```

**Output:**
- `stochK`: %K line (0-100)
- `stochD`: %D line (smoothed %K)
- `stochAbove50`: Boolean (stochK > 50)
- `stochBelow50`: Boolean (stochK < 50)

---

### 6. ADX (Average Directional Index)

```javascript
function calculateADX(candles, period = 14) {
    const results = [];
    const trueRanges = [];
    const plusDMs = [];
    const minusDMs = [];
    
    for (let i = 0; i < candles.length; i++) {
        if (i === 0) {
            trueRanges.push(candles[i].high - candles[i].low);
            plusDMs.push(0);
            minusDMs.push(0);
            results.push({ diPlus: 0, diMinus: 0, adx: 25 });
            continue;
        }
        
        const high = candles[i].high;
        const low = candles[i].low;
        const prevHigh = candles[i-1].high;
        const prevLow = candles[i-1].low;
        const prevClose = candles[i-1].close;
        
        // True Range
        const tr = Math.max(
            high - low,
            Math.abs(high - prevClose),
            Math.abs(low - prevClose)
        );
        trueRanges.push(tr);
        
        // Directional Movement
        const upMove = high - prevHigh;
        const downMove = prevLow - low;
        
        const plusDM = (upMove > downMove && upMove > 0) ? upMove : 0;
        const minusDM = (downMove > upMove && downMove > 0) ? downMove : 0;
        
        plusDMs.push(plusDM);
        minusDMs.push(minusDM);
        
        if (i < period) {
            results.push({ diPlus: 0, diMinus: 0, adx: 25 });
            continue;
        }
        
        // Smoothed values using Wilder's method
        const smoothedTR = wilderSmooth(trueRanges.slice(i - period + 1, i + 1));
        const smoothedPlusDM = wilderSmooth(plusDMs.slice(i - period + 1, i + 1));
        const smoothedMinusDM = wilderSmooth(minusDMs.slice(i - period + 1, i + 1));
        
        const diPlus = (smoothedPlusDM / smoothedTR) * 100;
        const diMinus = (smoothedMinusDM / smoothedTR) * 100;
        
        const dx = Math.abs(diPlus - diMinus) / (diPlus + diMinus) * 100;
        
        // ADX is smoothed DX
        // For simplicity, use running average of DX
        const adx = calculateRunningADX(dx, period, i, results);
        
        results.push({ diPlus, diMinus, adx });
    }
    
    return results;
}
```

**Output:**
- `diPlus`: +DI value
- `diMinus`: -DI value
- `adx`: ADX value (trend strength, 0-100)

---

### 7. Volume Ratio

```javascript
function calculateVolumeRatio(volumes, period = 20) {
    const sma = calculateSMA(volumes, period);
    
    return volumes.map((vol, i) => {
        return sma[i] > 0 ? vol / sma[i] : 1.0;
    });
}
```

**Output:**
- `volumeRatio`: Current volume / Average volume

---

### 8. Volatility Regime Detection

```javascript
function calculateVolatilityRegime(atrValues, percentilePeriod = 100) {
    const results = [];
    
    for (let i = 0; i < atrValues.length; i++) {
        if (i < percentilePeriod - 1) {
            results.push({ percentile: 50, regime: 'MEDIUM', multiplier: 1.0 });
            continue;
        }
        
        // Count how many values in the lookback are less than current
        const lookback = atrValues.slice(i - percentilePeriod + 1, i + 1);
        const current = atrValues[i];
        const countLess = lookback.filter(v => v < current).length;
        const percentile = (countLess / percentilePeriod) * 100;
        
        let regime, multiplier;
        if (percentile > 75) {
            regime = 'HIGH';
            multiplier = 0.85;  // Reduce scores in high volatility
        } else if (percentile < 25) {
            regime = 'LOW';
            multiplier = 1.15;  // Boost scores in low volatility
        } else {
            regime = 'MEDIUM';
            multiplier = 1.0;
        }
        
        results.push({ percentile, regime, multiplier });
    }
    
    return results;
}
```

**Output:**
- `atrPercentile`: 0-100 percentile rank
- `volRegime`: 'HIGH' | 'MEDIUM' | 'LOW'
- `volMultiplier`: Score adjustment factor (0.85, 1.0, or 1.15)

---

### 9. Dynamic Threshold

Based on ADX, determines the minimum prediction percentage needed for a "PERFECT TIME" signal.

```javascript
function calculateDynamicThreshold(adx) {
    if (adx > 30) return 55;      // Strong trend: lower threshold
    if (adx > 25) return 60;      // Good trend
    if (adx > 20) return 65;      // Moderate trend
    return 70;                     // Weak trend: higher threshold
}
```

---

## Scoring System

Each indicator produces a score from 0-100 based on how bullish or bearish the signal is.

### MACD Scoring

```javascript
function scoreMacdLong(macdLine, signalLine, histogram) {
    if (macdLine > signalLine && histogram > 0) return 100;  // Strong bullish
    if (macdLine > signalLine) return 70;                     // Bullish
    if (histogram > 0) return 50;                             // Weak bullish
    return 20;                                                 // Bearish
}

function scoreMacdShort(macdLine, signalLine, histogram) {
    if (macdLine < signalLine && histogram < 0) return 100;  // Strong bearish
    if (macdLine < signalLine) return 70;                     // Bearish
    if (histogram < 0) return 50;                             // Weak bearish
    return 20;                                                 // Bullish
}
```

### RSI Scoring

```javascript
function scoreRsiLong(rsi) {
    if (rsi < 30) return 100;      // Oversold - strong buy
    if (rsi < 40) return 85;
    if (rsi < 50) return 70;
    if (rsi < 60) return 50;
    return 25;                      // Overbought - weak buy
}

function scoreRsiShort(rsi) {
    if (rsi > 70) return 100;      // Overbought - strong sell
    if (rsi > 60) return 85;
    if (rsi > 50) return 70;
    if (rsi > 40) return 50;
    return 25;                      // Oversold - weak sell
}
```

### Stochastic Scoring

```javascript
function scoreStochLong(stochK, stochD) {
    if (stochK > stochD && stochK < 20) return 100;  // Oversold + bullish cross
    if (stochK > stochD && stochK < 50) return 85;   // Bullish below midline
    if (stochK > stochD) return 65;                   // Bullish
    return 25;                                         // Bearish
}

function scoreStochShort(stochK, stochD) {
    if (stochK < stochD && stochK > 80) return 100;  // Overbought + bearish cross
    if (stochK < stochD && stochK > 50) return 85;   // Bearish above midline
    if (stochK < stochD) return 65;                   // Bearish
    return 25;                                         // Bullish
}
```

### Volume Scoring

```javascript
function scoreVolume(volumeRatio) {
    if (volumeRatio > 2.0) return 100;   // Very high volume
    if (volumeRatio > 1.5) return 80;
    if (volumeRatio > 1.0) return 60;
    if (volumeRatio > 0.8) return 45;
    return 25;                            // Low volume
}
```

### Volume Delta Scoring

```javascript
function scoreDeltaLong(delta, deltaEma, deltaMomentum) {
    if (delta > 0 && deltaMomentum) return 100;      // Strong buying
    if (delta > 0) return 75;                         // Buying
    if (delta > -Math.abs(deltaEma)) return 40;      // Weak selling
    return 20;                                         // Strong selling
}

function scoreDeltaShort(delta, deltaEma, deltaMomentum) {
    if (delta < 0 && !deltaMomentum) return 100;     // Strong selling
    if (delta < 0) return 75;                         // Selling
    if (delta < Math.abs(deltaEma)) return 40;       // Weak buying
    return 20;                                         // Strong buying
}
```

### ADX Scoring

```javascript
function scoreADX(adx) {
    if (adx > 35) return 100;    // Very strong trend
    if (adx > 30) return 85;
    if (adx > 25) return 70;
    if (adx > 20) return 50;
    return 30;                    // Weak/no trend
}
```

### Trend Scoring

```javascript
function scoreTrendLong(isUptrend, ema8, ema21, ema50) {
    if (isUptrend && ema8 > ema21 && ema21 > ema50) return 100;  // Perfect alignment
    if (isUptrend && ema8 > ema21) return 80;                     // Good alignment
    if (isUptrend) return 60;                                      // Basic uptrend
    return 0;                                                       // Downtrend
}

function scoreTrendShort(isDowntrend, ema8, ema21, ema50) {
    if (isDowntrend && ema8 < ema21 && ema21 < ema50) return 100;  // Perfect alignment
    if (isDowntrend && ema8 < ema21) return 80;                     // Good alignment
    if (isDowntrend) return 60;                                      // Basic downtrend
    return 0;                                                         // Uptrend
}
```

---

## Weighted Score Calculation

```javascript
function calculateFinalScores(scores, weights, volMultiplier) {
    // Calculate raw weighted score
    const longScoreRaw = 
        (scores.trendLong * weights.trend) +
        (scores.macdLong * weights.macd) +
        (scores.deltaLong * weights.delta) +
        (scores.rsiLong * weights.rsi) +
        (scores.stochLong * weights.stoch) +
        (scores.adx * weights.adx) +
        (scores.volume * weights.volume);
    
    const shortScoreRaw = 
        (scores.trendShort * weights.trend) +
        (scores.macdShort * weights.macd) +
        (scores.deltaShort * weights.delta) +
        (scores.rsiShort * weights.rsi) +
        (scores.stochShort * weights.stoch) +
        (scores.adx * weights.adx) +
        (scores.volume * weights.volume);
    
    // Apply volatility multiplier and clamp
    const longScore = Math.round(Math.min(100, Math.max(0, longScoreRaw * volMultiplier)));
    const shortScore = Math.round(Math.min(100, Math.max(0, shortScoreRaw * volMultiplier)));
    
    // Convert to percentages
    const total = longScore + shortScore;
    const longPct = total > 0 ? Math.round((longScore / total) * 100) : 50;
    const shortPct = 100 - longPct;
    
    return { longScore, shortScore, longPct, shortPct };
}
```

---

## Confluence System

The 8-point confluence system counts how many indicators agree on direction.

### Long Confluence Points

```javascript
function calculateConfluenceLong(indicators, config) {
    let points = 0;
    
    // Point 1: Supertrend is bullish
    if (indicators.isUptrend) points++;
    
    // Point 2: Fast EMA above Medium EMA
    if (indicators.ema8 > indicators.ema21) points++;
    
    // Point 3: MACD line above Signal line
    if (indicators.macdLine > indicators.signalLine) points++;
    
    // Point 4: Stochastic %K above %D
    if (indicators.stochK > indicators.stochD) points++;
    
    // Point 5: Volume above minimum threshold
    if (indicators.volumeRatio >= config.minVolumeRatio) points++;
    
    // Point 6: ADX above trend threshold
    if (indicators.adx > config.adxThreshold) points++;
    
    // Point 7: RSI above 50
    if (indicators.rsi > 50) points++;
    
    // Point 8: Volume Delta bullish
    if (indicators.deltaBullish) points++;
    
    return points;  // Out of 8
}
```

### Short Confluence Points

```javascript
function calculateConfluenceShort(indicators, config) {
    let points = 0;
    
    // Point 1: Supertrend is bearish
    if (indicators.isDowntrend) points++;
    
    // Point 2: Fast EMA below Medium EMA
    if (indicators.ema8 < indicators.ema21) points++;
    
    // Point 3: MACD line below Signal line
    if (indicators.macdLine < indicators.signalLine) points++;
    
    // Point 4: Stochastic %K below %D
    if (indicators.stochK < indicators.stochD) points++;
    
    // Point 5: Volume above minimum threshold
    if (indicators.volumeRatio >= config.minVolumeRatio) points++;
    
    // Point 6: ADX above trend threshold
    if (indicators.adx > config.adxThreshold) points++;
    
    // Point 7: RSI below 50
    if (indicators.rsi < 50) points++;
    
    // Point 8: Volume Delta bearish
    if (indicators.deltaBearish) points++;
    
    return points;  // Out of 8
}
```

---

## Final Prediction Logic

### Perfect Time Conditions

"PERFECT TIME" represents the highest confidence signal when ALL conditions align.

```javascript
function checkPerfectTimeLong(indicators, scores, config) {
    const dynamicThreshold = calculateDynamicThreshold(indicators.adx);
    
    return (
        indicators.isUptrend &&                              // Supertrend bullish
        scores.longPct >= dynamicThreshold &&                // Prediction meets threshold
        indicators.confluenceLong >= config.minConfluence && // Minimum confluence
        indicators.volumeRatio >= config.minVolumeRatio &&   // Volume confirmation
        indicators.rsi > 50 &&                               // RSI above midline
        indicators.deltaBullish                              // Delta confirmation (V4 CRITICAL)
    );
}

function checkPerfectTimeShort(indicators, scores, config) {
    const dynamicThreshold = calculateDynamicThreshold(indicators.adx);
    
    return (
        indicators.isDowntrend &&                             // Supertrend bearish
        scores.shortPct >= dynamicThreshold &&                // Prediction meets threshold
        indicators.confluenceShort >= config.minConfluence && // Minimum confluence
        indicators.volumeRatio >= config.minVolumeRatio &&    // Volume confirmation
        indicators.rsi < 50 &&                                // RSI below midline
        indicators.deltaBearish                               // Delta confirmation (V4 CRITICAL)
    );
}
```

### Buy/Sell Signal Conditions

Separate from "PERFECT TIME" - these trigger on EMA crossovers.

```javascript
function checkBuySignal(current, previous) {
    const emaCrossover = previous.ema8 <= previous.ema21 && current.ema8 > current.ema21;
    return emaCrossover && current.isUptrend && current.deltaBullish;
}

function checkSellSignal(current, previous) {
    const emaCrossunder = previous.ema8 >= previous.ema21 && current.ema8 < current.ema21;
    return emaCrossunder && current.isDowntrend && current.deltaBearish;
}
```

---

## Master Prediction Function

```javascript
function generatePrediction(candles, config) {
    // Ensure we have enough data
    if (candles.length < 100) {
        throw new Error('Insufficient historical data. Need at least 100 candles.');
    }
    
    // Calculate all indicators
    const closes = candles.map(c => c.close);
    const volumes = candles.map(c => c.volume);
    
    const supertrend = calculateSupertrend(candles, config.stFactor, config.stPeriod);
    const volumeDelta = calculateVolumeDelta(candles, config.deltaEmaPeriod);
    const ema8 = calculateEMA(closes, config.emaFast);
    const ema21 = calculateEMA(closes, config.emaMid);
    const ema50 = calculateEMA(closes, config.emaSlow);
    const rsi = calculateRSI(closes, config.rsiPeriod);
    const macd = calculateMACD(closes, config.macdFast, config.macdSlow, config.macdSignal);
    const stoch = calculateStochastic(candles, config.stochPeriod, config.stochSmooth);
    const adxData = calculateADX(candles, config.adxPeriod);
    const volumeRatio = calculateVolumeRatio(volumes, config.volumeSmaPeriod);
    const atr = calculateATR(candles, config.atrLength);
    const volRegime = calculateVolatilityRegime(atr, config.atrPercentilePeriod);
    
    // Get latest values (last index)
    const i = candles.length - 1;
    
    const current = {
        // Supertrend
        isUptrend: supertrend[i].isUptrend,
        isDowntrend: supertrend[i].isDowntrend,
        
        // EMAs
        ema8: ema8[i],
        ema21: ema21[i],
        ema50: ema50[i],
        
        // Momentum
        rsi: rsi[i],
        macdLine: macd.macdLine[i],
        signalLine: macd.signalLine[i],
        histogram: macd.histogram[i],
        stochK: stoch.stochK[i],
        stochD: stoch.stochD[i],
        
        // Volume
        volumeRatio: volumeRatio[i],
        delta: volumeDelta[i].delta,
        deltaEma: volumeDelta[i].deltaEma,
        deltaMomentum: volumeDelta[i].deltaMomentum,
        deltaBullish: volumeDelta[i].deltaBullish,
        deltaBearish: volumeDelta[i].deltaBearish,
        
        // Trend Strength
        adx: adxData[i].adx,
        diPlus: adxData[i].diPlus,
        diMinus: adxData[i].diMinus,
        
        // Volatility
        atr: atr[i],
        volRegime: volRegime[i].regime,
        volMultiplier: volRegime[i].multiplier
    };
    
    // Calculate scores
    const scores = {
        trendLong: scoreTrendLong(current.isUptrend, current.ema8, current.ema21, current.ema50),
        trendShort: scoreTrendShort(current.isDowntrend, current.ema8, current.ema21, current.ema50),
        macdLong: scoreMacdLong(current.macdLine, current.signalLine, current.histogram),
        macdShort: scoreMacdShort(current.macdLine, current.signalLine, current.histogram),
        rsiLong: scoreRsiLong(current.rsi),
        rsiShort: scoreRsiShort(current.rsi),
        stochLong: scoreStochLong(current.stochK, current.stochD),
        stochShort: scoreStochShort(current.stochK, current.stochD),
        deltaLong: scoreDeltaLong(current.delta, current.deltaEma, current.deltaMomentum),
        deltaShort: scoreDeltaShort(current.delta, current.deltaEma, current.deltaMomentum),
        adx: scoreADX(current.adx),
        volume: scoreVolume(current.volumeRatio)
    };
    
    // Calculate final weighted scores
    const finalScores = calculateFinalScores(scores, config.weights, current.volMultiplier);
    
    // Calculate confluence
    current.confluenceLong = calculateConfluenceLong(current, config);
    current.confluenceShort = calculateConfluenceShort(current, config);
    
    // Check perfect time conditions
    const longPerfect = checkPerfectTimeLong(current, finalScores, config);
    const shortPerfect = checkPerfectTimeShort(current, finalScores, config);
    
    // Determine primary prediction
    let prediction, confidence, signal;
    
    if (longPerfect) {
        prediction = 'UP';
        confidence = 'PERFECT_TIME';
        signal = 'STRONG_LONG';
    } else if (shortPerfect) {
        prediction = 'DOWN';
        confidence = 'PERFECT_TIME';
        signal = 'STRONG_SHORT';
    } else if (finalScores.longPct >= 60) {
        prediction = 'UP';
        confidence = 'MODERATE';
        signal = 'LEAN_LONG';
    } else if (finalScores.shortPct >= 60) {
        prediction = 'DOWN';
        confidence = 'MODERATE';
        signal = 'LEAN_SHORT';
    } else {
        prediction = 'NEUTRAL';
        confidence = 'LOW';
        signal = 'NO_TRADE';
    }
    
    return {
        timestamp: new Date().toISOString(),
        symbol: candles[i].symbol,
        
        // Primary Output
        prediction,           // 'UP' | 'DOWN' | 'NEUTRAL'
        confidence,           // 'PERFECT_TIME' | 'MODERATE' | 'LOW'
        signal,              // Signal type
        
        // Probabilities
        upProbability: finalScores.longPct,
        downProbability: finalScores.shortPct,
        
        // Confluence
        longConfluence: current.confluenceLong,
        shortConfluence: current.confluenceShort,
        maxConfluence: 8,
        
        // Perfect Time Flags
        longPerfectTime: longPerfect,
        shortPerfectTime: shortPerfect,
        
        // Key Indicators
        indicators: {
            trend: current.isUptrend ? 'UPTREND' : 'DOWNTREND',
            rsi: Math.round(current.rsi),
            adx: Math.round(current.adx),
            volumeRatio: Math.round(current.volumeRatio * 100) / 100,
            volRegime: current.volRegime,
            deltaBias: current.deltaBullish ? 'BULLISH' : 'BEARISH'
        },
        
        // Component Scores (for debugging/transparency)
        componentScores: scores,
        
        // Config used
        config: {
            minConfluence: config.minConfluence,
            adxThreshold: config.adxThreshold,
            dynamicThreshold: calculateDynamicThreshold(current.adx)
        }
    };
}
```

---

## Output Schema

### Supabase Table: `predictions`

```sql
CREATE TABLE predictions (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Target
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    prediction_window_minutes INT NOT NULL,
    
    -- Primary Prediction
    prediction VARCHAR(10) NOT NULL,      -- 'UP', 'DOWN', 'NEUTRAL'
    confidence VARCHAR(20) NOT NULL,      -- 'PERFECT_TIME', 'MODERATE', 'LOW'
    signal VARCHAR(20) NOT NULL,
    
    -- Probabilities (for Polymarket)
    up_probability INT NOT NULL,          -- 0-100
    down_probability INT NOT NULL,        -- 0-100
    
    -- Confluence
    long_confluence INT NOT NULL,
    short_confluence INT NOT NULL,
    
    -- Perfect Time Flags
    long_perfect_time BOOLEAN DEFAULT FALSE,
    short_perfect_time BOOLEAN DEFAULT FALSE,
    
    -- Key Indicators (JSONB for flexibility)
    indicators JSONB,
    component_scores JSONB,
    
    -- For backtesting
    candle_close_price DECIMAL(20, 8),
    actual_result VARCHAR(10),            -- Fill in after 15 min
    result_price DECIMAL(20, 8),
    was_correct BOOLEAN,
    
    -- Indexing
    UNIQUE(symbol, timeframe, created_at)
);

CREATE INDEX idx_predictions_symbol_time ON predictions(symbol, created_at DESC);
CREATE INDEX idx_predictions_confidence ON predictions(confidence);
```

---

## Implementation Notes

### 1. Timing Considerations

For Polymarket 15-minute predictions:
- Run prediction at the **close** of each 15-minute candle
- The prediction is for the **next** 15-minute period
- Example: At 10:15:00, predict direction from 10:15 to 10:30

### 2. Data Freshness

```javascript
// Ensure latest candle is recent
const lastCandle = candles[candles.length - 1];
const ageMs = Date.now() - new Date(lastCandle.timestamp).getTime();
const maxAgeMs = 15 * 60 * 1000; // 15 minutes

if (ageMs > maxAgeMs) {
    throw new Error('Stale data: last candle is too old');
}
```

### 3. Polymarket Integration

For "UP or DOWN in 15 minutes" binary markets:

```javascript
// Convert prediction to Polymarket position
function getPolymarketPosition(prediction) {
    if (prediction.longPerfectTime) {
        return { side: 'YES_UP', confidence: 'HIGH', size: 'LARGE' };
    }
    if (prediction.shortPerfectTime) {
        return { side: 'YES_DOWN', confidence: 'HIGH', size: 'LARGE' };
    }
    if (prediction.upProbability >= 65) {
        return { side: 'YES_UP', confidence: 'MEDIUM', size: 'MEDIUM' };
    }
    if (prediction.downProbability >= 65) {
        return { side: 'YES_DOWN', confidence: 'MEDIUM', size: 'MEDIUM' };
    }
    return { side: 'NO_TRADE', confidence: 'LOW', size: 'NONE' };
}
```

### 4. Backtesting Query

```sql
-- Check prediction accuracy
SELECT 
    confidence,
    COUNT(*) as total,
    SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as correct,
    ROUND(100.0 * SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) / COUNT(*), 2) as accuracy_pct
FROM predictions
WHERE actual_result IS NOT NULL
GROUP BY confidence
ORDER BY accuracy_pct DESC;
```

### 5. Scheduled Execution

```javascript
// Run every 15 minutes at candle close
// Cron: */15 * * * *

async function scheduledPrediction() {
    const symbols = ['BTC', 'ETH', 'SOL'];  // Your target symbols
    
    for (const symbol of symbols) {
        const candles = await fetchCandles(symbol, '15m', 100);
        const prediction = generatePrediction(candles, CONFIG);
        await savePrediction(prediction);
    }
}
```

---

## Quick Reference: Indicator Thresholds

| Indicator | Bullish | Bearish | Neutral |
|-----------|---------|---------|---------|
| RSI | < 50 (buy signal stronger < 30) | > 50 (sell signal stronger > 70) | ~50 |
| Stochastic | %K > %D | %K < %D | %K ≈ %D |
| MACD | Line > Signal | Line < Signal | Crossing |
| ADX | > 25 (trending) | > 25 (trending) | < 20 (ranging) |
| Volume | > 1.0x average | > 1.0x average | < 0.8x average |
| Delta | > 0 (buying) | < 0 (selling) | ~0 |
| Supertrend | Price > Line | Price < Line | At line |
| EMA Stack | 8 > 21 > 50 | 8 < 21 < 50 | Mixed |

---

## Summary Flow

```
1. FETCH 100 candles of OHLCV data
              ↓
2. CALCULATE all 8 indicators
              ↓
3. SCORE each indicator (0-100)
              ↓
4. WEIGHT & COMBINE scores
              ↓
5. APPLY volatility multiplier
              ↓
6. CALCULATE confluence points
              ↓
7. CHECK Perfect Time conditions
              ↓
8. OUTPUT prediction with probabilities
```