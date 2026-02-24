# V4 Analysis: Alpha V4 Ensemble Model

**A Post-Mortem of Overengineering and the Curse of Dimensionality**

---

## Abstract

V4 represents the most ambitious and ultimately most disappointing iteration of the Polymarket prediction system. It was a textbook case of overengineering: the development team attempted to improve on V3 by combining three separate models (XGBoost, LightGBM, Neural Network) into an ensemble, expanding the feature set from 53 to 272 features (a 5x increase), and adding 16 synthetic market regime indicators. The result was catastrophic.

Validation performance degraded sharply compared to V3:
- **15-minute models**: 62-65% validation accuracy (vs V3's 75-80%)
- **1-hour models**: 52-53% validation accuracy (vs V3's 78-80%)

Live performance was even worse, with four of six models posting negative Sharpe ratios and calibration errors so high (0.10-0.36) that the models' confidence estimates had almost zero correlation with actual accuracy. The system demonstrated conclusively that adding noise through indiscriminate feature expansion cannot create predictive signal where none exists.

**Key Takeaway**: V4 failed because it confused complexity with capability. More features do not automatically translate to better predictions. The ensemble approach magnified weaknesses rather than diversified them. The 1-hour models were effectively broken on arrival at validation stage.

---

## Executive Summary: The Numbers Don't Lie

### Validation Performance by Timeframe

| Model | Validation Accuracy | Validation AUC | Test Accuracy | Purged CV |
|-------|-------------------|-----------------|---------------|-----------|
| **BTC 15m** | 62.49% | 0.675 | 58.96% | 63.51% |
| **ETH 15m** | 62.84% | 0.688 | 62.20% | 63.19% |
| **SOL 15m** | 64.72% | 0.698 | 63.27% | 63.93% |
| **BTC 1h** | 52.63% | 0.540 | 50.55% | 54.00% |
| **ETH 1h** | 52.99% | 0.547 | 49.39% | 53.59% |
| **SOL 1h** | 53.22% | 0.539 | 52.15% | 52.13% |

### Live Performance (Feb 4-6, 2026)

**15-minute Models (HIGH Confidence Predictions Only)**:
- BTC HIGH DOWN: 53.85% accuracy (52 predictions)
- BTC HIGH UP: 42.03% accuracy (70 predictions)
- ETH HIGH DOWN: 54.72% accuracy (54 predictions)
- ETH HIGH UP: 44.05% accuracy (84 predictions)
- SOL HIGH DOWN: 51.72% accuracy (58 predictions)
- SOL HIGH UP: 38.30% accuracy (48 predictions)

**1-hour Models**:
- Mostly LOW confidence with 37-44% accuracy
- Only bright spot: SOL 1h HIGH DOWN at 75.00% (8 predictions) and SOL 1h HIGH UP at 69.23% (13 predictions)

### Sharpe Ratio Summary

| Model | Avg Sharpe | Calibration Error | Status |
|-------|-----------|------------------|--------|
| BTC 15m | -0.409 | 0.252 | Negative return |
| BTC 1h | -0.904 | 0.228 | Severe losses |
| ETH 15m | +0.847 | 0.226 | Minimal gains, broken calibration |
| ETH 1h | -0.810 | 0.360 | Severe losses + worst calibration |
| SOL 15m | -0.259 | 0.205 | Negative return |
| SOL 1h | +0.681 | 0.101 | Only passing grade (low sample) |

---

## System Architecture

### Declared Intent

V4 was designed with the following ambitions:

1. **Ensemble Voting**: Combine three independent models to reduce single-model variance
   - XGBoost: gradient boosting with regularization
   - LightGBM: faster gradient boosting with tree-based feature selection
   - Neural Network: nonlinear feature interactions

2. **Massive Feature Expansion**: Grow from 53 to 272 features to capture more market regime patterns
   - Base indicator percentile ranks (160+ features across 3 windows: 20th, 50th, 100th)
   - Slope calculations (80+ features across 5 periods: 3, 5, 10, 15, 20 bars)
   - Synthetic regime flags (16 new indicators)
   - Cross-pair correlations and market structure metrics

3. **Synthetic Indicators**: Add domain-knowledge-driven features to detect market regimes
   - `syn_trend_strength`: continuous 0-100 scale
   - `syn_volatility_regime`: categorical 1-3 (low/medium/high)
   - `syn_market_structure`: bull/bear/range
   - `syn_momentum_divergence`: binary flag
   - `syn_volume_anomaly`: binary flag
   - Support/resistance proximity
   - Liquidation zones, order imbalance, VWAP deviation, session bias

4. **Rigorous Validation**: Implement purged cross-validation to prevent look-ahead bias and data leakage

### Data Specifications

**Training Data**:
- 15-minute models: 154,678 samples (2021-2025)
- 1-hour models: 38,671 samples (2021-2025)
- Label distribution skewed toward DOWN on SOL (45.47% UP vs ~50% baseline)

**Feature Count**:
- 272 total features (vs V3's 53)
- Percentile ranks: ~160 features (multiple window depths)
- Slopes: ~80 features (5 different periods)
- Regime indicators: ~16 synthetic features
- Temporal and cross-pair: remaining features

**Prediction Volume**:
- 759 total predictions between Feb 4-6, 2026
- Across 6 models (BTC/ETH/SOL × 15m/1h)
- Confidence distribution: ~60% HIGH, ~20% MED, ~20% LOW

---

## Critical Failures

### 1. The Curse of Dimensionality

Going from 53 to 272 features (a 512% increase) while training on only 154,678 samples for 15m and 38,671 for 1h created a severe signal-to-noise problem.

**The Math**:
- 15m model: ~154K samples ÷ 272 features ≈ 567 samples per feature
- This is insufficient for robust feature learning without aggressive regularization
- With regularization strong enough to prevent overfitting, the model loses the ability to learn any actual patterns

**What Happened**:
- The ensemble was forced to memorize noise in the training set
- Feature importance was distributed thinly across many irrelevant features
- The models never learned a generalizable signal

**Evidence**:
- V3 with 53 features achieved 75-80% validation accuracy on 15m
- V4 with 272 features achieved 62-65% on the same task
- Test accuracy dropped from ~75% (V3) to ~60% (V4)

### 2. The Ensemble Disaster

A key principle of ensemble learning is that member models should be diverse AND accurate. V4 violated both principles:

**The Problem**:
- Individual models (before ensembling) were likely weaker than V3's single XGBoost model
- Averaging three weak models produces one weak model, not a strong one
- Diversity only helps if the underlying signal is learnable

**Evidence from Calibration Errors**:
- BTC 1h: 0.228 calibration error (model says 75% confidence, actually right 50% of time)
- ETH 1h: 0.360 calibration error (worst in dataset)
- This indicates the ensemble's probability estimates were completely unreliable

**The Lesson**:
Ensembling weak learners does not produce strong learners. It produces confident weak learners. V4 was that—the models were confidently wrong across many predictions.

### 3. 1-Hour Models Were Broken on Arrival

With 52-53% validation accuracy, the 1-hour models never had a real edge:

| Model | Val Acc | Test Acc | Interpretation |
|-------|---------|----------|-----------------|
| BTC 1h | 52.63% | 50.55% | Coin flip |
| ETH 1h | 52.99% | 49.39% | Slightly worse than coin flip |
| SOL 1h | 53.22% | 52.15% | Barely above coin flip |

**Why 1h Failed**:
1. Hourly price moves have weaker autocorrelation than 15-minute moves
2. More data (38K samples) is required to learn hourly patterns, but feature count was the same
3. The synthetic indicators were optimized for shorter timeframes
4. 272 features with 38K training samples is even worse signal-to-noise than 15m

### 4. Calibration: The Confidence Trap

High calibration error means the model's confidence estimates are worthless as probability calibrators:

- A model saying "80% confident in UP" that's right only 50% of the time is worse than a model saying "60% confident"
- V4's models suffered from severe miscalibration across the board
- This made position sizing impossible—the Kelly criterion and EV calculations based on these probabilities were fundamentally flawed

**Example**:
- BTC 15m made 52 HIGH DOWN predictions with 53.85% accuracy
- But the ensemble reported these with ~75% confidence (based on averaging 3 models that agreed)
- The true confidence was closer to 53%—the model was 22 percentage points too confident

### 5. Synthetic Indicators: Incomplete Implementation

The synthetic indicators were not fully developed:
- Slope components were not applied across all synthetic features
- This meant the regime detection was operating on partial information
- Signals that could have been distinct were diluted

---

## Live Performance Disaster

### 15-Minute Models: Underwhelming

With only 38-54% accuracy on HIGH confidence predictions, the system was barely better than random:

**BTC 15m**:
- HIGH DOWN: 53.85% (52 preds) - barely above 50%
- HIGH UP: 42.03% (70 preds) - below 50%
- Net result: money-losing

**ETH 15m**:
- HIGH DOWN: 54.72% (54 preds) - marginal edge
- HIGH UP: 44.05% (84 preds) - below 50%
- Net result: money-losing

**SOL 15m**:
- HIGH DOWN: 51.72% (58 preds) - no edge
- HIGH UP: 38.30% (48 preds) - significantly below 50%
- Net result: severe money-losing

### 1-Hour Models: Effectively Non-Functional

Most 1h predictions were LOW confidence with 37-44% accuracy. Only SOL 1h showed any edge:
- SOL 1h HIGH DOWN: 75.00% (8 predictions)
- SOL 1h HIGH UP: 69.23% (13 predictions)

But with only 21 total HIGH confidence 1h predictions across all pairs, this is statistically insufficient and likely noise.

### Sharpe Ratio Analysis

| Model | Sharpe | Interpretation |
|-------|--------|-----------------|
| BTC 15m | -0.409 | Lose money consistently |
| BTC 1h | -0.904 | Lose money fast |
| ETH 15m | +0.847 | Barely profitable, unreliable |
| ETH 1h | -0.810 | Lose money fast |
| SOL 15m | -0.259 | Lose money slowly |
| SOL 1h | +0.681 | Barely profitable (insufficient data) |

**Four out of six models had negative Sharpe ratios**. In a functioning prediction system, you'd expect at least 5/6 or better.

---

## Root Cause Analysis

### What Worked (Minimally)

1. **Infrastructure**: V4's database schema was well-designed
   - Proper performance logging with calibration error tracking
   - Pipeline run tracking
   - Schema migrations for version control
   - This was production-ready in structure, just not in output

2. **Synthetic Indicator Concept**: The idea was sound
   - Market regime detection is real and valuable
   - Volatility regimes, trend strength, momentum divergence are legitimate features
   - Implementation was incomplete, but the concept was right

3. **Purged Cross-Validation**: Using temporally separated validation sets was correct
   - This prevented look-ahead bias
   - The purged CV scores (63-64% for 15m, 52-54% for 1h) were more honest than validation accuracy

### What Catastrophically Failed

1. **Feature Explosion Without Feature Selection**
   - 272 features without aggressive dimensionality reduction
   - No feature importance analysis to prune irrelevant features
   - No automatic feature selection (e.g., L1 regularization, recursive elimination)
   - Added 219 new features without justifying that each had signal

2. **Ensemble Without Validation**
   - Three weak models were averaged without checking if they were actually diverse
   - No analysis of correlation between member model predictions
   - If all three models make the same mistakes, averaging doesn't help

3. **1-Hour Feature Set Didn't Scale Down**
   - Used the same 272 features for 1-hour predictions
   - Features optimized for 15-minute frequency don't necessarily work for 1-hour
   - Should have built a separate 1-hour feature set from scratch

4. **Ignored V3 Warning Signs**
   - V3 already showed weakness on 1-hour models (78-80%)
   - V4 made this worse (52-53%)
   - Should have investigated 1h model failure in V3 instead of pushing forward

5. **Calibration Not Addressed Until Live**
   - High calibration errors should have been a red flag in validation
   - Probability calibration methods (Platt scaling, isotonic regression) weren't applied
   - Position sizing was based on uncalibrated probabilities

6. **Incomplete Implementation**
   - Synthetic indicator slopes not fully applied
   - System shipped with partial features
   - This degraded the regime detection that was supposed to be the edge

---

## Comparative Analysis: V3 vs V4

### Architecture Comparison

| Aspect | V3 | V4 |
|--------|----|----|
| Base Model | Single XGBoost | Ensemble (XGBoost + LightGBM + NN) |
| Feature Count | 53 | 272 |
| Percentile Windows | Limited | 3 windows (20, 50, 100) |
| Slope Periods | 3, 5, 10 | 3, 5, 10, 15, 20 |
| Synthetic Indicators | None | 16 new indicators |
| Validation CV | Standard | Purged (temporally separated) |

### Performance Comparison

| Metric | V3 15m | V4 15m | V3 1h | V4 1h |
|--------|--------|--------|-------|-------|
| Val Accuracy | 75-80% | 62-65% | 78-80% | 52-53% |
| Test Accuracy | ~75% | ~60% | ~78% | ~50% |
| Live Accuracy | Moderate (~55-60%) | Poor (~45-54%) | Unknown | Terrible (~37-44%) |
| Sharpe (Live) | +0.2 to +0.8 | -0.3 to +0.8 | Unknown | -0.8 to +0.7 |

**Verdict**: V4 was worse at every stage—validation, test, and live.

---

## Design Decisions That Doomed V4

### 1. "More Data, More Features"

The team believed:
- Expanding from 53 to 272 features would capture patterns V3 missed
- Three models with different architectures would reduce variance

Reality:
- 272 features with ~150K training samples is a p >> n problem
- Ensemble voting on weak models produces weak predictions with false confidence
- The 15m models lost 13-18 percentage points of validation accuracy

### 2. "One Feature Set to Rule Them All"

The team used identical features for both 15m and 1h predictions.

Reality:
- 15-minute price moves are driven by momentum and short-term order flow
- 1-hour moves are driven by broader market structure and macro events
- The same features can't optimally represent both timescales
- 1h validation accuracy never rose above 53%

### 3. "Synthetic Indicators Will Find the Edge"

The team added 16 new synthetic features hoping they would identify regime changes.

Reality:
- Incomplete implementation (missing slope components)
- Not properly validated before deployment
- Regime changes are real, but they need to be measured accurately
- Quick-and-dirty synthetic features added noise instead

### 4. "Validation Accuracy Above 50% Means the Model Works"

The team shipped with 52-53% validation accuracy on 1h models.

Reality:
- This is a coin flip
- With proper cross-validation, this should have been rejected outright
- No edge = no deployment

---

## Lessons from V4's Failure

### The Hard Truths

1. **Complexity Is Not Your Friend**
   - V3's simpler approach with 53 features and 1 model outperformed V4's ensemble with 272 features
   - If you can't explain why a feature should predict price, it probably doesn't
   - Every new feature adds noise until proven otherwise

2. **Ensemble Learning Requires Strong Base Models**
   - Bagging/boosting/averaging only works if member models have signal
   - Three weak models = one weak model with false confidence
   - You need at least 2/3 of your ensemble to be individually profitable

3. **1-Hour Predictions Are Harder Than 1-Minute**
   - Don't assume features that work at one frequency work at another
   - Hourly moves are less predictable than minute-by-minute moves
   - V4's 1h models were garbage on arrival

4. **Calibration Matters as Much as Accuracy**
   - A model at 60% accuracy with perfect calibration is more useful than 65% accuracy with 0.3 calibration error
   - When your confidence estimates are wrong, position sizing breaks
   - Kelly criterion depends on accurate probability estimates

5. **Validation-to-Live Gap Is Real**
   - V4 showed 62-65% validation on 15m but only 40-55% live
   - This is a 15-25 percentage point drop
   - Overfitting on training data, poor feature stability, regime shift, or all three

6. **Incomplete Features Should Never Ship**
   - Synthetic indicator slopes were left unimplemented
   - System shipped with partial features
   - This destroyed the signal that partial features might have contained

---

## What Should Have Happened

### Pre-Deployment Checkpoints

1. **Validation Accuracy Gate**: 
   - 15m models: require ≥70% accuracy (V4 had 62-65%)
   - 1h models: require ≥65% accuracy (V4 had 52-53%)
   - V4 should have been rejected at this gate

2. **Ensemble Diversity Check**:
   - Measure correlation between member model predictions
   - Verify that each member contributes unique information
   - Reject if models are >0.8 correlated

3. **Feature Justification**:
   - Explain why each of 219 new features was added
   - Perform feature importance analysis
   - Prune any feature with <1% relative importance

4. **Calibration Validation**:
   - Apply Platt scaling or isotonic regression
   - Verify calibration error < 0.1
   - V4's 0.22-0.36 calibration errors should have triggered alarm

5. **Out-of-Sample Testing**:
   - Test on data from different market conditions
   - V4's live performance showed it hadn't learned generalizable patterns

### Iterative Improvement Path

1. **Start simpler**: Keep V3 as baseline
2. **Add features thoughtfully**: Justify each new feature with domain logic
3. **Measure what matters**: Track Sharpe ratio, not just accuracy
4. **Validate rigorously**: Purged CV on multiple time periods
5. **Build confidence slowly**: Deploy with small capital allocation
6. **Learn from feedback**: When live performance differs from validation, investigate

---

## Conclusion: A Cautionary Tale

V4 was a well-intentioned but ultimately misguided attempt to improve a crypto price prediction system through complexity and ensemble voting. The team's core assumptions were flawed:

- More features ≠ better predictions
- Ensemble voting ≠ noise reduction
- High validation accuracy ≠ live edge

The result was a system that:
- Lost money on 4 out of 6 models (negative Sharpe ratios)
- Was confidently wrong due to miscalibration
- Performed worse than the simpler V3 at every stage
- Shipped with incomplete features

The fundamental problem: **The team was trying to extract signal from noise**. With 272 features and ~150K training samples on one axis, they created a massive overfitting problem. Regularization prevented memorization but also prevented learning. The ensemble magnified this by averaging three weak models.

For crypto price prediction to work, you need:
1. A real edge (features that actually predict price)
2. Enough data to learn it without overfitting
3. Honest validation that simulates live trading conditions
4. Proper calibration
5. Sufficient statistical power (>65% accuracy on hold-out test sets)

V4 had none of these. It was a reminder that machine learning is not a tool that can turn noise into gold. It can only extract signal if signal exists in the data.

**The next iteration (V5, if it exists) should:**
- Return to V3's feature set as a baseline
- Add features conservatively with clear justification
- Build a dedicated 1h model from scratch (don't copy 15m features)
- Implement proper probability calibration
- Establish clear deployment gates (e.g., ≥70% val accuracy required)
- Test on live data in small increments before scaling

Complexity was V4's enemy. Simplicity and discipline should be the next iteration's foundation.

---

## Technical Specifications (Reference)

### Database Schema (alpha_v4)

**Core Tables**:
- `models`: 6 rows (BTC/ETH/SOL × 15m/1h)
- `features_15m` / `features_1h`: Feature metadata and descriptions
- `raw_features_15m` / `raw_features_1h`: Raw numeric feature vectors
- `labels`: 657K rows of binary UP/DOWN labels
- `predictions`: 759 predictions with confidence scores
- `performance_log`: 3,672 performance tracking entries
- `synthetic_indicators`: 612 rows of market regime indicators
- `pipeline_runs`: Execution history and metadata
- `schema_migrations`: Version control for schema changes

### Feature Categories (272 Total)

1. **Percentile Ranks** (~160 features)
   - Windows: 20th, 50th, 100th percentile
   - For: price, volume, momentum, volatility indicators

2. **Slope Features** (~80 features)
   - Periods: 3, 5, 10, 15, 20 bars
   - For: trend direction and strength

3. **Synthetic Indicators** (~16 features)
   - Trend strength, volatility regime, market structure
   - Momentum divergence, volume anomaly
   - Support/resistance proximity
   - Liquidation zone, order imbalance, VWAP deviation, session bias

4. **Temporal Features**
   - Hour of day, day of week, market session
   - Time-based momentum and seasonality

5. **Cross-Pair Features**
   - Correlations: BTC-ETH, BTC-SOL, ETH-SOL (and reversed)

### Live Prediction Distribution (759 Total)

**By Confidence Tier**:
- HIGH: ~456 predictions (60%)
- MED: ~152 predictions (20%)
- LOW: ~151 predictions (20%)

**By Model**:
- BTC 15m: 122 predictions
- ETH 15m: 138 predictions
- SOL 15m: 106 predictions
- BTC 1h: 109 predictions
- ETH 1h: 110 predictions
- SOL 1h: 174 predictions (highest volume)

---

**Document Version**: 1.0  
**Analysis Date**: February 6, 2026  
**Data Period**: System deployment through Feb 6, 2026 live predictions
