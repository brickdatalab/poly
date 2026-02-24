# Discovery: CVD + EMA Spread Sigma Sweeps (Training Schema, BTC 15m Events)

Date: 2026-02-11

Run outputs:
- `/Users/vitolo/Desktop/projects/poly/scripts/output/indicator_sigma_sweeps/20260211T014920Z`

## Goal
Find any **single-indicator** signal (CVD ROC or EMA spread ROC) that can predict the **next 15-minute window outcome** (Up/Down) with:
- **Accuracy >= 70%**
- **Coverage >= 0.5%**

If the gate is not met on **global training schema data**, we do **not** proceed to indicator-schema validation.

## Dataset / Event Definition
- Symbol: `BTC` only (SOL excluded; ETH not part of this sweep)
- Events: all 15-minute windows starting at `:00/:15/:30/:45`
- Target label: direction of the 15m event window (Up/Down) from `t0` open to `t0+14m` close

No-leakage alignment:
- Feature timestamp `t_feat = t0 - 15m` (last fully completed 15m candle before the event begins).

## Indicators Tested
### 1) CVD ROC (from `training.spot_15m_indicators.cvd_50`)
Feature:
- `x = cvd_50(t_feat) - cvd_50(t_feat - lookback)`

Lookback variants:
- `15m` (1 candle)
- `60m` (4 candles)

Normalization variants:
- `global`: mu/sd over full training history
- `rolling 21d`: mu/sd over the prior 21 days at each event, with `min_n in {500, 1000}`

Sigma ladder (both sides):
- `0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0`

Result:
- All operating points hovered around **~48% to ~52% accuracy**, including rolling normalization.
- **No operating point met** the (>=70% accuracy, >=0.5% coverage) gate.

Representative example (global, 15m lookback):
- `cvd_50_roc__lb15m__global`: best accuracies were ~51.5% (DOWN/UP tails) and mostly ~49%.

### 2) EMA Spread ROC (from `training.spot_15m_indicators.ema_9` and `.ema_21`)
Intermediate:
- `spread_pct = ((ema_9 - ema_21) / ema_21) * 100`

Feature:
- `x = spread_pct(t_feat) - spread_pct(t_feat - lookback)`

Lookback variants:
- `15m`
- `60m`

Normalization variants:
- `global`
- `rolling 21d` with `min_n in {500, 1000}`

Sigma ladder:
- `0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0`

Result:
- EMA spread ROC performed **worse than random** in many regimes (often **~43% to ~48% accuracy**).
- Rolling normalization did not materially improve results.
- **No operating point met** the (>=70% accuracy, >=0.5% coverage) gate.

## Conclusion
On **global training schema**:
- `cvd_50` ROC (15m/60m, global/rolling) shows **no actionable directional correlation** for 15m event outcomes.
- `ema_9/ema_21` spread ROC (15m/60m, global/rolling) shows **no actionable directional correlation** for 15m event outcomes.

Action:
- Mark both indicators as **ruled out** for this style of single-indicator sigma-threshold flagging (as implemented here).
- Do **not** apply these two to indicator-schema “real-world” validation (gate not met in training).

