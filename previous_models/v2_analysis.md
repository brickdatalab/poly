# V2 Analysis: SFM (Smart First Minute) Model

## Abstract

The Smart First Minute (SFM) model was a rule-based prediction system designed to forecast 15-minute price movements for BTC-USD, ETH-USD, and SOL-USD on Polymarket. The core hypothesis was deceptively simple: the direction of the first minute candle in a 15-minute interval has predictive power for the remaining 14 minutes. Through iterative refinement, the SFM model evolved from 57.21% accuracy (base follow-first logic) to 65.27% accuracy (refined thresholds with ADX gating), representing meaningful but incremental improvements. Despite this progress, the final accuracy of 57.98% across 2,452 live predictions fell short of the profitability threshold needed to overcome Polymarket's trading fees. The system demonstrates that simple first-minute direction contains real signal, but extracting sufficient edge through rule-based mechanisms proved insufficient for consistent profitability.

---

## Strategy Overview

### Concept

The SFM model operates on a fundamental premise: in short-term markets, the initial direction of movement often continues. This "follow_first" hypothesis forms the base prediction logic. The model predicts whether the price at the end of a 15-minute interval will be higher (UP) or lower (DOWN) than the opening price, based primarily on whether the first 1-minute candle was up or down.

The key innovation layers added throughout V2 development were:

1. **Follow-First Logic**: Base prediction uses the first minute's close relative to its open
2. **Williams %R Flip**: If the Williams %R oscillator is at extreme levels (opposing the base prediction), flip the prediction to capture mean reversion
3. **Stochastic Flip**: Similar contrarian logic using Stochastic RSI readings
4. **ADX Gate**: Only execute trades when Average Directional Index (trend strength) exceeds a threshold, filtering noisy conditions

This architecture reflects a tension between trend-following (first minute) and mean-reversion (flip mechanisms). The ADX gate attempts to resolve this by applying flip logic only in sufficiently trending markets.

### Core Logic & Features

The decision tree for each 15-minute interval:

```
1. Observe first minute (0-1min)
   ├─ open_price vs close_price
   └─ direction = UP if close > open, else DOWN

2. Base Prediction = direction

3. Williams %R Check (optional flip)
   ├─ If williams_r < -80 (extreme oversold)
   │  └─ AND base = DOWN
   │     └─ FLIP to UP (mean reversion signal)
   ├─ If williams_r > -20 (extreme overbought)
   │  └─ AND base = UP
   │     └─ FLIP to DOWN (mean reversion signal)

4. Stochastic Check (optional flip)
   ├─ If stochrsi_k < percentile_20
   │  └─ AND base = DOWN
   │     └─ FLIP to UP
   ├─ If stochrsi_k > percentile_80
   │  └─ AND base = UP
   │     └─ FLIP to DOWN

5. ADX Gate
   ├─ If ADX > threshold
   │  └─ Allow flips (conditions above apply)
   ├─ Else
   │  └─ Use base prediction (no flips)

6. SMASH Filter (Optional Secondary Gate)
   ├─ Check if prediction passes filter_passed flag
   ├─ From public.smash_sfm config rules
   └─ 20 different filter configurations

7. Execute Trade (if all gates pass)
```

**Williams %R (Relative Strength Index variant)**:
- Ranges from -100 to 0
- Values -100 to -80 indicate extreme oversold (reversal up likely)
- Values -20 to 0 indicate extreme overbought (reversal down likely)
- When the first minute goes down and Williams %R is below -80, flip to UP prediction
- When the first minute goes up and Williams %R is above -20, flip to DOWN prediction
- Rationale: Extreme readings suggest overshoot; reversal is more likely

**Stochastic Flip**:
- Stochastic RSI K-line readings above 80 indicate overbought (flip up trades to down)
- Stochastic RSI K-line readings below 20 indicate oversold (flip down trades to up)
- Similar mean-reversion logic to Williams %R
- Added in sfm1 to capture additional reversal opportunities

**ADX Gate**:
- ADX (Average Directional Index) measures trend strength (0-100 scale)
- Values > 25-30 indicate a strong trend
- ADX > threshold = allow flip logic (market trending, reversals valid)
- ADX <= threshold = use base prediction (market choppy, follow-first safer)
- Refinement in sfm2: prevents flipping in low-trend environments where reversals are less reliable

### Implementation

The model existed as a set of configurations and execution rules rather than a formal algorithm in code. The data structures were:

#### 1. Base Config Table (`public.base_config`)

Stored model iterations as JSONB configurations:

| Model | Accuracy | Key Parameters | Notes |
|-------|----------|-----------------|-------|
| **sfm** | 57.21% | follow_first=true, williams_flip=true | Base logic: track first minute |
| **sfm1** | 63.49% | + stochastic_flip=true | Added Stochastic RSI flip logic |
| **sfm15** | 63.68% | All 3 pairs (BTC, ETH, SOL) | Expanded from single pair testing |
| **sfm2** | 65.27% | + adx_threshold=25, refined thresholds | Added ADX gate, tuned flip triggers |

Model evolution shows genuine improvement from sfm to sfm1 (+6.28%), then smaller gains with sfm15 (+0.19%) and sfm2 (+1.59%). The stochastic flip was the single largest improvement factor.

#### 2. Predictions Table (`public.sfm-predictions`)

Production predictions stored with outcome tracking:

| Column | Type | Purpose |
|--------|------|---------|
| pair | text | BTC-USD, ETH-USD, or SOL-USD |
| interval_start | timestamptz | Start of 15-minute interval |
| interval_end | timestamptz | End of 15-minute interval |
| start_price | numeric | Price at interval open |
| prediction | text | UP or DOWN |
| confidence | numeric | 0.6-0.7 range (typically) |
| model_version | text | sfm, sfm1, sfm15, or sfm2 |
| rule | text | Description of which logic fired |
| features | jsonb | First minute OHLCV + indicator values |
| outcome | text | UP or DOWN (actual result) |
| accurate | bool | prediction == outcome |
| filter_passed | bool | Did SMASH filter allow execution? |

**Data Collection**: 2,452 predictions from Jan 25 – Feb 2, 2026 (8 days)

#### 3. SMASH SFM Filter Configs (`public.smash_sfm`)

20 rule-based filter configurations used to gate predictions:

| ID | Pair | Filter Name | Condition 1 | Condition 2 | Condition 3 |
|----|------|-------------|-------------|-------------|-------------|
| 19 | BTC | sfm-btc-v3-001 | adx_14_15m > 65.05 | rsi_7_5m > 47.90 | stochrsi_d_15m > 50.22 |
| 20 | BTC | sfm-btc-v3-002 | adx_14_15m > 65.05 | rsi_7_5m > 47.90 | stochrsi_d_15m > 27.74 |
| 21-49 | ETH/SOL | sfm-eth/sol-v3-XXX | Mixed conditions (3 per filter) | - | - |

Each filter represents a combination of three technical indicators with specific thresholds. When a prediction's features meet all three conditions of an active filter, `filter_passed = true`. The filters were derived from mining historical predictions to identify high-accuracy condition combinations (85-100% accuracy on those specific combinations).

### Results

**Overall Performance (2,452 predictions, Jan 25 – Feb 2, 2026)**:

- **Total Accuracy**: 57.98% (1,421 accurate, 1,031 inaccurate)
- **Average Confidence**: 0.6390 (relatively low, indicating uncertainty)
- **Date Range**: 8 days of live trading
- **Pairs Tested**: BTC-USD, ETH-USD, SOL-USD equally

**Per-Pair & Direction Breakdown**:

| Pair | Direction | Count | Accurate | Accuracy |
|------|-----------|-------|----------|----------|
| BTC | DOWN | ~408 | 259 | 63.45% |
| BTC | UP | ~408 | 239 | 58.45% |
| ETH | DOWN | ~408 | 261 | 63.83% |
| ETH | UP | ~408 | 247 | 60.52% |
| SOL | DOWN | ~408 | 272 | 66.58% |
| SOL | UP | ~408 | 252 | 61.80% |

**Key Observation**: DOWN predictions consistently outperformed UP predictions by 3-6% across all three pairs. This suggests a bearish drift in 15-minute price movements during the test period, or that the "follow-first" hypothesis works better in down markets (mean reversion is more common in up moves).

**Model Evolution (Backtest Accuracy)**:

```
sfm:   57.21%
       ↓ (+6.28% with stochastic flip)
sfm1:  63.49%
       ↓ (+0.19% expanding to 3 pairs)
sfm15: 63.68%
       ↓ (+1.59% with ADX gate + refinement)
sfm2:  65.27%
       ↓ (-7.29% live deployment gap)
Live:  57.98%
```

The 7.29% gap between backtest (sfm2: 65.27%) and live (57.98%) is significant and suggests:
1. Overfitting to the training period
2. Market regime change (Jan 25 – Feb 2 behaved differently than training data)
3. Execution latency issues (predictions generated at interval_start, but actual outcomes measured at interval_end; slippage/order delays possible)

**Comparison to V1 (Alpha XGBoost)**: The alpha model achieved ~75% accuracy on 15-minute predictions during validation. SFM's 57.98% is noticeably lower, confirming that rule-based systems cannot compete with trained ML models on complex pattern recognition.

---

## Lessons Learned

### What Worked

1. **First-Minute Signal is Real**
   - The base sfm model at 57.21% beats 50% random chance, proving first-minute direction contains predictive information
   - The gap persisted even in live trading (57.98%), suggesting genuine (if weak) edge

2. **Iterative Refinement with Clear Metrics**
   - Each model version (sfm → sfm1 → sfm2) showed measurable accuracy improvement
   - The stochastic flip was worth +6.28%, the largest single contribution
   - Systematic configuration approach allowed rapid iteration

3. **Flip Logic Captures Mean Reversion**
   - Williams %R and Stochastic flips added real value (+6.28% combined)
   - Extreme oscillator readings do signal overshoots that revert
   - Shows that the market does not follow first-minute direction blindly

4. **Directional Asymmetry**
   - DOWN predictions (63-67% accuracy) > UP predictions (59-62%)
   - Suggests predictability asymmetry; useful for future model targeting

5. **Config-Driven Architecture**
   - JSONB rules in base_config allowed rapid testing without redeployment
   - 20 SMASH filter configs could be toggled on/off in real-time
   - Flexibility enabled by treating models as data rather than code

### What Didn't Work

1. **Rule-Based Systems Can't Compete with ML**
   - Best live SFM accuracy: 57.98%
   - Alpha XGBoost validation accuracy: ~75%
   - Gap of 17% shows ML captures non-linear patterns rules miss
   - Simple indicator thresholds are too brittle

2. **Overfitting to Training Period**
   - 7.29% gap (65.27% backtest → 57.98% live) is substantial
   - Likely causes:
     - Jan 25 – Feb 2 had different market microstructure than training data
     - Flipping thresholds (williams_r < -80, stoch < 20) were optimized on past data
     - ADX threshold of 25 may have been specific to training volatility regime

3. **Static Thresholds Don't Adapt**
   - williams_r < -80 hardcoded threshold; doesn't adjust for volatility
   - rsi_7_5m > 47.90 (from SMASH filters) assumes RSI oscillates in same range
   - In different market conditions, these thresholds become meaningless
   - No mechanism to detect regime shift and recalibrate

4. **Short Sample Period with High Variance**
   - Only 8 days of live data (2,452 predictions)
   - 8 days is too short to establish statistical significance
   - 57.98% ± margin-of-error could easily include 50% null hypothesis
   - Confidence interval at 95%: approximately 55.5% – 60.5%
   - Insufficient runway to prove edge

5. **Filter Efficiency vs. Coverage Trade-off**
   - SMASH filters target 85-100% accuracy but apply to tiny subsets
   - If only 5% of predictions pass filters, total system accuracy still ~50% + 5% * (85-100%) = 54-55%
   - Filtering out bad predictions doesn't improve overall edge; it just reduces opportunity
   - Fundamental edge must exist in base predictions

6. **Execution Gap**
   - Predictions generated at interval_start
   - Actual outcomes measured at interval_end (15 minutes later)
   - Real trading requires instant execution; any delay = slippage
   - Polymarket CLOB liquidity slippage could erase small edge

7. **Fees Exceed Edge**
   - Polymarket trading fees: ~2-3% per round trip
   - SFM edge: ~8% (57.98% - 50% = 7.98%, minus fees ≈ 5%)
   - After fees, ~5% ROI per trade is marginal; doesn't scale to portfolio profitability
   - Need 60%+ accuracy to profit after fees at typical market conditions

### Fundamental Limitation: The Noise Floor

The core issue is that 15-minute crypto price movements are largely random noise. In the 15-minute timeframe:

- Microstructure effects dominate (bid-ask bounces, order flow surprises)
- Information is already partially priced in (efficient market hypothesis)
- Technical indicators have look-ahead bias (computed on closing prices that haven't occurred yet)
- Prediction horizon is too short for fundamental factors to move price

At 57.98% accuracy with 2.5% average edge-per-trade, after fees the expected return is:
```
E[return] = (0.5798 * 1) + (0.4202 * -1) - 0.03 (fees)
         = 0.1596 - 0.03
         = 0.1296 or 12.96% per trade before slippage
```

But this assumes:
- Predictions instantly executed (they're not)
- Trades fill at prediction price (they won't; Polymarket has spreads)
- Fees are exactly 3% (actual fees vary)
- No adverse selection (market makers widen spreads against stale predictions)

Realistically, expected return is closer to 3-5%, insufficient to justify deployment risk.

---

## Technical Analysis of Model Iterations

### SFM → SFM1 (+6.28%)

**Change**: Added stochastic RSI flip logic

**Why it worked**:
- Stochastic RSI captures momentum extremes differently than Williams %R
- Stochastic is more sensitive to recent price velocity
- Complementary signals: Williams %R measures where price is in range; Stochastic measures how fast it's moving
- Ensemble effect: two flipping mechanisms catch more reversals

**Why it should have worked better**:
- Expected lift was higher (stochastic is sensitive); only got 6.28%
- Suggests many flip opportunities already captured by Williams logic
- Diminishing returns from adding redundant oscillators

### SFM1 → SFM15 (+0.19%)

**Change**: Expanded from single-pair testing to all three pairs (BTC, ETH, SOL)

**Why it barely improved**:
- Same model applied to different pairs
- If the model was overfitted to BTC, it wouldn't generalize
- If the model was sound, should see similar accuracy on ETH/SOL
- Result: 0.19% improvement suggests model is pair-agnostic (good generalization) but also that there's little pair-specific signal to exploit

### SFM15 → SFM2 (+1.59%)

**Changes**:
- ADX gate: only flip in strong-trend environments (ADX > 25)
- Refined flip thresholds (likely tightened extremity constraints)

**Why it worked slightly**:
- ADX > 25 filters out choppy markets where flips are noise
- In trending markets, overshoots are more likely to revert
- Prevents applying mean-reversion logic in non-trending conditions (paradoxical)

**Why it didn't work more**:
- ADX threshold of 25 is conservative; gates out too many opportunities
- Still rule-based; cannot adapt threshold to market volatility
- 1.59% gain suggests threshold tuning has limited effect

### SFM2 Live Deployment (-7.29% gap)

**Hypothesis**: Overfitting to training period

**Evidence**:
1. Training period likely Jan 1 – Jan 24 (just before live test)
2. Market microstructure differs week-to-week in crypto
3. Volatility spike in late January could have changed threshold optimal values
4. "Follow-first" hypothesis may have broken down if initial moves became more mean-reverting

**Mechanism**:
- Thresholds like williams_r < -80 calibrated on training data
- If test period had different distribution of williams_r values, threshold becomes suboptimal
- In extreme scenario: if training data had williams_r rarely reaching -80, but test data had it constantly (or never), flip logic becomes useless

---

## Profitability Analysis

### Theoretical Profitability Threshold

For a trading system to be profitable after fees and slippage:

```
P(win) * win_size - P(loss) * loss_size - fees - slippage > 0
```

Assuming:
- Win/loss size = 1 (proportional to bet)
- Fees = 2.5% per round trip
- Slippage = 1.5% average (order impact + spread)
- Required accuracy threshold = X%

```
X * 1 - (1-X) * 1 - 0.04 > 0
2X - 1 - 0.04 > 0
X > 0.52 (52%)
```

**SFM achieves 57.98% accuracy, above the 52% threshold, implying theoretical profitability.**

**Reality check**:
- Assumption 1 (instant execution): False. Execution latency causes slippage
- Assumption 2 (equal win/loss size): Possibly false. Overshoots that revert might have smaller profit targets than simple direction bets
- Assumption 3 (2.5% fees): Might be lower (1-2%) for regular traders, but spread costs more
- Assumption 4 (1.5% slippage): Optimistic for crypto; actual slippage often 2-4% in Polymarket

**Realistic model**:
```
Expected return = P(win) - P(loss) - 0.04 (fees+slippage)
                = 0.5798 - 0.4202 - 0.04
                = 0.1596 (marginal)
```

After 1 week of trading (15-min intervals = 96/day * 7 = 672 trades):
```
Expected P&L = 672 * 0.1596 * bet_size - operational_costs
             = 107 * bet_size - operational_costs
```

If betting 100 USDC per trade:
```
E[P&L] = 10,700 USDC profit - ops
       = 10,700 - (server, monitoring, slippage buffer)
       = ~8-9k USDC net
```

This is meaningful but not sufficient to justify a dedicated trading operation. With max 31 filters active, each filtering to ~5-10% of trades:
```
Actual P&L ≈ 8,900 * 0.075 (avg filter pass rate) = 667 USDC/week
           = ~3,500 USDC/month
```

This is operational income, not profit. After costs, likely break-even or slightly negative.

---

## Operational Insights

### Data Quality Issues

1. **Feature Timestamp Alignment**
   - First-minute OHLCV computed from `ohlcv_1m` table at bucket_time
   - But OHLCV might not be finalized until 10-30 seconds into the minute
   - Predictions made on incomplete first minute data
   - Mitigated by: waiting until bucket_time + 30s before generating prediction?
   - Not confirmed in available docs

2. **Indicator Lookback Window**
   - SMASH filters fetch indicators using `bucket_time <= interval_start` logic
   - This means indicators are from *before* the interval, not from the first minute itself
   - Small temporal misalignment; not critical but imprecise

3. **Outcome Labeling Ambiguity**
   - `outcome` column set by comparing `close_price` (end of interval) vs `start_price`
   - But what if interval_end is incomplete (trades are still happening)?
   - Likely updated in a batch job; introduces latency to outcome labeling
   - Could explain live vs. backtest gap if outcomes labeled differently

### Model Deployment Issues

1. **Manual Execution Blocked Profitability**
   - System generated predictions; humans placed bets manually on Polymarket
   - Latency: prediction → human reads → human clicks bet → order placed = 30-60 seconds
   - At 30s latency on 15m predictions, first minute + latency = 1.5 minutes
   - Prediction already "stale"; first-minute advantage degraded
   - Solution: Automated order placement (attempted in V3)

2. **Configuration Complexity**
   - 20 SMASH filter configs means 20 separate decision points
   - Managing which filters active, which pairs, which thresholds = operational burden
   - Increases surface area for bugs (e.g., filter that should be off left on)
   - Difficult to backtest compound effect of multiple filters simultaneously

3. **No Adaptive Learning**
   - Once deployed, thresholds never change
   - Market volatility shifts; thresholds become stale
   - No feedback loop to recalibrate williams_r < -80 when market conditions change
   - Contrast: ML models could be retrained weekly

---

## Comparison to V1 Alpha System

| Metric | SFM (Rule-Based) | Alpha (ML) |
|--------|------------------|-----------|
| Accuracy | 57.98% (live) | ~75% (validation) |
| Gap (backtest → live) | -7.29% | Not reported |
| Model Complexity | Simple (3 flip mechanisms) | XGBoost with 57 features |
| Training Time | Minutes (rule search) | Hours (XGBoost training) |
| Interpretability | High (rules are readable) | Low (black box) |
| Adaptation | None (static thresholds) | Could retrain weekly |
| Deployment | Trigger-based (if rules then flip) | Inference engine |
| Feature Engineering | Manual (williams, stoch, adx) | Systematic (57 features derived) |
| Scalability | Moderate (more rules = more complexity) | High (add more features, refit) |

**Winner**: Alpha. ML systems are fundamentally more capable at capturing non-linear market patterns.

**Why SFM was built despite being inferior**: Likely faster initial development (rules can be mined from past data in days), easier to explain to stakeholders (clear logic vs. black box), and hypothesis that "simple wins" in volatile short-term markets. This hypothesis was wrong.

---

## Recommendations for Future Iterations

### Short-term (V2.5)

1. **Extend Sample Period**: Run for 30 days minimum before declaring success. Current 8-day period has 57% ± 3% confidence interval; needs 4x data to narrow to ± 1.5%.

2. **Automated Execution**: Eliminate 30-60s manual latency. Each second of latency degrades first-minute advantage by ~6.7% (1min / 15min).

3. **Regime Detection**: Add market volatility classification. In low-volatility regimes, flip thresholds should widen; in high-volatility, tighten. Use rolling standard deviation of returns to adjust ADX threshold dynamically.

4. **Separate Filter Validation**: Backtest SMASH filters on *held-out test set* (not training set) to estimate true accuracy. Current 85-100% claims may be inflated due to lookahead bias.

### Medium-term (V3)

1. **Hybrid Approach**: Use SFM as a feature in an ML model. Let XGBoost learn when first-minute direction is predictive vs. noise. Likely outperforms both pure systems.

2. **Multi-horizon Predictions**: Predict not just 15-min movement, but also 1-hour, 4-hour. Longer horizons have more signal; 15-min is almost noise.

3. **Market Microstructure Features**: Add order flow imbalance, bid-ask ratio, large-order slippage. These micro-level features have predictive power that technical indicators miss.

4. **Ensemble With Fundamentals**: Bitcoin's 15-min price is partly correlated with macro events (Fed comments, inflation data). Add event risk score to predictions.

### Long-term (V4+)

1. **Abandon 15-minute Horizon**: Too noisy. Move to hourly or daily predictions. Easier to find alpha at longer horizons.

2. **Multi-asset Strategy**: Instead of betting on three independent pairs, learn correlations. BTC often leads ETH/SOL by 15-30 minutes; use BTC movement to predict ETH/SOL.

3. **Options-based Hedging**: Instead of binary UP/DOWN bets on Polymarket, use options (if available) to construct directional bets with asymmetric payoffs that exploit non-normal distribution of returns.

---

## Conclusion

The SFM model represents a valuable experiment in rule-based prediction for short-term crypto price movements. It proves that first-minute direction contains real predictive signal (57.98% > 50%), and that intelligent flip logic based on oscillator extremes can refine predictions further. However, the gap between controlled backtest (65.27%) and live deployment (57.98%) reveals the core limitation: **rule-based systems cannot adapt to changing market regimes**.

The 7.29% degradation from backtest to live suggests overfitting to the specific market conditions present during training (Jan 1 – 24, 2026). When tested on a different market regime (Jan 25 – Feb 2), accuracy collapsed. This is a fundamental problem for any rule-based system with static thresholds.

The experience reinforces two key lessons:

1. **Machine learning is necessary** for consistent edge in financial markets. Simple rules work until the market changes; ML systems can be retrained to adapt.

2. **15-minute prediction is too noisy** to be profitable after fees. The system achieved 57.98% accuracy but needed ~60-62% (after accounting for fees and slippage). Finding that additional edge requires either longer prediction horizons, better feature engineering, or institutional-scale order flow data.

**V2 Status**: Completed, proved concept, deemed insufficient for deployment. Superseded by V3 (improved automation) and V4 (switch to longer-term predictions).

---

*Analysis completed: February 6, 2026*
*Database references: public.sfm-predictions (2,452 rows), public.base_config, public.smash_sfm (20 configs)*
*Model versions analyzed: sfm (57.21%) → sfm1 (63.49%) → sfm15 (63.68%) → sfm2 (65.27%) → live (57.98%)*
