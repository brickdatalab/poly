# V1 Analysis: GPT-5.2 Calibration Model

## Abstract

V1 represented an early-stage attempt to predict 15-minute directional price movements (UP/DOWN) for three cryptocurrency pairs (BTC-USD, ETH-USD, SOL-USD) on Polymarket using an LLM-based approach. The system leveraged Claude/GPT-5.2 to generate directional predictions, which were then filtered through a calibration model organized into 15 price-movement-magnitude bins per pair. These predictions were further gated by 30 rule-based filter configurations (the "smash" filters) that applied hardcoded indicator thresholds before execution.

The system accumulated 5,050 predictions over an 18-day period (January 15 - February 2, 2026) with an overall accuracy of 54.11%, compared to a 50% baseline for random coin-flip predictions. While marginally better than random, this performance falls well below the profitability threshold required to overcome Polymarket trading fees (~2%), making the system economically unviable. The modest edge revealed fundamental limitations in using language models for quantitative price prediction without proper statistical and pattern recognition frameworks.

## Strategy Overview

### Concept

The foundational premise of V1 was that large language models possess sufficient reasoning capability to identify directional price movements based on recent market data and contextual information. Rather than relying exclusively on statistical models or technical indicators, V1 attempted to harness LLM "intuition" to detect patterns that might be missed by traditional quantitative approaches.

The core insight was that predictions could be improved through calibration: by organizing historical prediction errors into magnitude bins, the system could learn which prediction confidence levels corresponded to actual accuracy. A prediction with 65% confidence in a particular price-move bin might have demonstrated 62% historical accuracy in that bin, allowing for calibration and potential adjustment of strategy parameters (e.g., whether to follow the initial prediction or take a contrarian position).

However, this approach fundamentally misunderstood the problem domain. Price prediction is not a reasoning task where an LLM's language comprehension and logical inference provide an advantage. It is a statistical pattern recognition problem operating on noisy, high-dimensional market microstructure data. The calibration layer could not overcome the core inadequacy of the prediction source.

### Core Logic & Features

The V1 system operated through a multi-stage pipeline:

1. **LLM Prediction Generation**: Claude/GPT-5.2 generated directional predictions (UP/DOWN) for each pair, along with a confidence score (typically 0.0-1.0 range). The model operated on recent OHLCV data and potentially other market context.

2. **Calibration Binning**: Predictions were stored in `public.gpt52_calibration` with 15 distinct bins per trading pair. These bins were organized by the magnitude of the actual realized price movement:
   - Example bins for BTC-USD: `-0.60%_to_-0.45%`, `-0.45%_to_-0.30%`, `-0.30%_to_-0.15%`, `-0.15%_to_0.00%`, `0.00%_to_0.15%`, `0.15%_to_0.30%`, `0.30%_to_0.45%`, `0.45%_to_0.60%`, etc.
   - Each bin stored the corresponding prediction accuracy and strategy parameter

3. **Strategy Parameters**: Each calibration bin specified one of two strategies:
   - `follow_first`: Execute the original LLM prediction as-is
   - `contra_prev`: Execute the opposite of the LLM prediction (take a contrarian position)
   
   This parameter was meant to be dynamically adjusted based on which strategy had historically performed better in that bin.

4. **Smash Filter Gating**: Before execution, all predictions were passed through a chain of 30 rule-based filter configurations. Each filter could contain up to 5 conditions applied to technical indicators:
   - **Available indicators**: MACD histogram, CVD (Cumulative Volume Delta) value, RSI (Relative Strength Index), Stochastic RSI (K), ADX (Average Directional Index), ATR (Average True Range), Bollinger Bandwidth, Williams %R, Ulcer Index, Trade Flow Imbalance
   - **Example conditions**: `macd_histogram < -2.0`, `cvd_value < -500`, `rsi < 30`, `stochrsi_k < 0.15`, `adx > 25`
   - **Logic**: A prediction was only executed if it passed all applicable filter conditions in the assigned configuration

5. **Execution**: Predictions that survived the filter chain were submitted to Polymarket for the 15-minute window.

### Implementation

The V1 system was built using a PostgreSQL database with the following key tables:

- **`public.gpt52_calibration`**: Stored calibration metadata. Indexed by pair (BTC-USD, ETH-USD, SOL-USD), move-magnitude bin, and direction (UP/DOWN). Contained fields for accuracy statistics per bin and the current strategy parameter (follow_first vs contra_prev).

- **`public."gpt52-predictions"`**: The main predictions table. Schema included:
  - Timestamp of prediction
  - Trading pair (BTC-USD, ETH-USD, SOL-USD)
  - Direction (UP/DOWN)
  - LLM confidence score
  - Actual price movement (15-minute)
  - Prediction accuracy (binary: correct or incorrect)
  - Assigned calibration bin
  - Applied smash filter configuration ID
  - Execution status and result

- **`public.smash`**: Filter configuration table. Contained 30 distinct configurations, each with up to 5 threshold conditions on various technical indicators. Filters were applied as AND gates—all conditions in a configuration had to pass for a prediction to execute.

The system relied on a **config-driven architecture**: rather than hard-coding prediction logic, all filtering rules were externalized to the `smash` table. This theoretically allowed for rapid iteration on filter parameters without code changes. In practice, this became a liability—filters were tuned based on historical backtests that did not hold up to live market conditions.

### Results

**Overall Performance Metrics:**
- **Total predictions**: 5,050
- **Date range**: January 15 - February 2, 2026 (18 days)
- **Overall accuracy**: 54.11%
- **Average confidence**: 0.6006
- **Baseline (random coin-flip)**: 50.00%
- **Edge above baseline**: 4.11 percentage points

**Per-Pair and Per-Direction Breakdown:**

| Pair | Direction | Accuracy |
|------|-----------|----------|
| BTC-USD | DOWN | 60.61% |
| BTC-USD | UP | 55.32% |
| ETH-USD | DOWN | 59.44% |
| ETH-USD | UP | 55.69% |
| SOL-USD | DOWN | 59.48% |
| SOL-USD | UP | 53.54% |

**Key Observation**: DOWN predictions consistently outperformed UP predictions across all three pairs. The average accuracy for DOWN predictions was 59.84%, versus 54.85% for UP predictions—a meaningful 5 percentage point gap. This suggests either:
1. The LLM had learned asymmetric patterns (easier to identify downward moves)
2. Market microstructure during the test period favored downward prediction
3. Calibration bins for DOWN moves happened to align better with live conditions

**Profitability Analysis:**

With Polymarket trading fees of approximately 2% per round-trip trade, the system would need accuracy of roughly 52% to break even. At 54.11% overall accuracy, the theoretical gross edge is marginal: 54.11% - 50% = 4.11 percentage points. After accounting for slippage, fees, and execution delays, the system likely loses money in practice.

Over 5,050 predictions, a 54.11% win rate at even odds would represent a ~207 unit gross profit. Trading fees would consume a significant portion of this. The lack of position sizing flexibility in a binary prediction market compounds the problem—each prediction has identical stake and payout structure.

### Lessons Learned

**What Worked:**

1. **Asymmetric Prediction Quality**: The consistent outperformance of DOWN predictions (59.84% vs 54.85%) demonstrates that directional bias exists and can be quantified. This asymmetry should have been weighted more heavily in model adjustments.

2. **Calibration Concept**: The idea of binning predictions by magnitude and tracking accuracy per bin was sound. It provided a framework for understanding prediction quality heterogeneity—some confidence levels genuinely correlated with higher accuracy than others.

3. **Multi-Stage Filtering**: The smash filter pipeline allowed for rapid experimentation with different gating logic. A more statistically rigorous filtering framework built on this foundation could have improved results.

**What Didn't Work:**

1. **54% Accuracy is Insufficient**: At the core, V1 fails the profitability test. A 54.11% win rate barely exceeds the break-even threshold when trading costs are factored in. The system generates no margin for error and collapses with even modest fee structures. This is the fundamental failure that dominates all other considerations.

2. **LLM Prediction Source is Inadequate**: Language models lack the inductive bias necessary for price prediction. LLMs excel at pattern matching in high-entropy, linguistic domains where context and reasoning apply. Financial markets, in contrast, are driven by latency-sensitive information processing and adversarial trading dynamics. An LLM cannot "reason" its way to edge in a market where faster, more specialized signal processors are always present.

3. **Static Calibration Bins Don't Adapt**: The 15-magnitude bins per pair were fixed at model training time. Market regimes change—volatility spikes, correlation structures shift, microstructure evolves. A static calibration built on January data does not remain valid in February. Adaptive binning or dynamic strategy selection was never implemented.

4. **Hardcoded Filter Thresholds are Brittle**: The 30 smash configurations used fixed indicator thresholds (e.g., `rsi < 30`, `adx > 25`). These thresholds are notorious for regime-dependence. RSI behavior at 8% volatility differs from RSI behavior at 25% volatility. The system had no mechanism to adjust thresholds based on current volatility regime or other market conditions.

5. **Indicator Overload Without Statistical Validation**: The system incorporated 10 different technical indicators with up to 5 conditions per filter. There was no investigation into which indicators were actually predictive, which were redundant, and which were adding noise. A proper feature importance analysis or correlation study was never conducted. This is cargo-cult quantitative trading: using many indicators with the vague hope that more signals equal better predictions.

6. **No Risk Management or Position Sizing**: The system made identical bets regardless of confidence level or predicted volatility. A 60% confidence prediction received the same capital allocation as a 51% confidence prediction. Proper risk management would size positions inversely to uncertainty, allocating more capital to high-conviction, low-volatility setups.

7. **Absence of Live vs. Backtest Validation**: The system appears to have been validated against historical backtests (the calibration bins were tuned this way). Live trading performance diverged from backtest assumptions—a common and destructive failure mode in automated trading. Cross-validation, walk-forward testing, and out-of-sample validation were not implemented.

8. **Fundamental Category Error**: The system attempted to solve a **statistical prediction problem** using a **language reasoning engine**. This is a category error. An LLM has no special capability to detect statistical patterns in market microstructure. The eventual solution will require proper statistical modeling, signal processing, and information theory—not prompting a chatbot to "reason about price movements."

**Recommendations for Future Iterations:**

1. Switch to statistical prediction models (gradient boosted trees, neural networks with proper time-series architecture) trained on relevant features
2. Implement regime detection and dynamic parameter adjustment rather than static calibration
3. Conduct rigorous feature engineering and importance analysis to eliminate noise
4. Use proper walk-forward validation and out-of-sample testing
5. Implement position sizing and risk management tied to confidence and volatility
6. Target accuracy thresholds of 55-60% minimum before considering deployment
7. Accept that market-making adversarial selection means the majority of edge comes from speed and information quality, not prediction sophistication

---

**Document Generated**: V1 Post-Mortem Analysis  
**System Period**: January 15 - February 2, 2026  
**Status**: Discontinued - Insufficient Edge for Profitability
