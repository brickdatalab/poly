# Window-Edge Boundary Momentum Discovery (BTC, ETH)

## What We Tested
We tested whether a short price move that straddles a 15m candle boundary predicts the direction of the *full* 15m candle.

For each 15m candle start `t0` (restricted to `:00`, `:15`, `:30`, `:45`):

- **Boundary move feature** (4-minute window around the boundary):
  - `pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100`
  - Examples:
    - `:57 -> :01` for `:00 -> :14`
    - `:12 -> :16` for `:15 -> :29`
    - `:27 -> :31` for `:30 -> :44`
    - `:42 -> :46` for `:45 -> :59`

- **Label / outcome**:
  - `outcome_up = 1` if the 15m candle closes up (`close@t0+14m > open@t0`), else `0`.
  - Flat candles excluded.

Data source: `training.spot_1m` + `training.spot_15m` (training schema only). SOL excluded.

## Dataset Size (Merged Across All Quarter-Hour Starts)
Each `t0` is treated as a unique event; all four quarter-hour segments are merged.

- BTC: `n = 106,622`, base up-rate `0.5017`
- ETH: `n = 100,709`, base up-rate `0.4994`

## Global Signal (Not a Full Model, Just “Is There A Relationship?”)
There is a real directional relationship:

- BTC: Pearson corr(`pct_diff`, `outcome_up`) = `0.1128`
- ETH: Pearson corr(`pct_diff`, `outcome_up`) = `0.1048`

Interpretation: the signal exists, but it’s not strong enough to be “one feature predicts everything”. The useful part is in the tails.

## Tail Rules (Sigma-Threshold Filters)
We computed per-symbol `mean(pct_diff)` and `stddev(pct_diff)` over the merged dataset.

Then evaluated these filters:

- **Down filter**: `pct_diff < mean - k*stddev`
- **Up filter**: `pct_diff > mean + k*stddev`

### BTC Results
**Down filter (predict DOWN)**
- `k=1.0`: match rate `6.7753%`, DOWN `61.9601%`, UP `38.0399%` (n=7,224)
- `k=1.5`: match rate `3.1757%`, DOWN `63.8807%`, UP `36.1193%` (n=3,386)
- `k=2.0`: match rate `1.7210%`, DOWN `65.5586%`, UP `34.4414%` (n=1,835)

**Up filter (predict UP)**
- `k=1.0`: match rate `6.9367%`, UP `64.0346%`, DOWN `35.9654%` (n=7,396)
- `k=1.5`: match rate `3.4646%`, UP `66.0801%`, DOWN `33.9199%` (n=3,694)
- `k=2.0`: match rate `1.9452%`, UP `67.2131%`, DOWN `32.7869%` (n=2,074)

### ETH Results
**Down filter (predict DOWN)**
- `k=1.0`: match rate `7.0758%`, DOWN `60.6792%`, UP `39.3208%` (n=7,126)
- `k=1.5`: match rate `3.3493%`, DOWN `62.5556%`, UP `37.4444%` (n=3,373)
- `k=2.0`: match rate `1.7983%`, DOWN `64.8261%`, UP `35.1739%` (n=1,811)

**Up filter (predict UP)**
- `k=1.0`: match rate `7.3588%`, UP `63.5002%`, DOWN `36.4998%` (n=7,411)
- `k=1.5`: match rate `3.6283%`, UP `65.7635%`, DOWN `34.2365%` (n=3,654)
- `k=2.0`: match rate `2.0187%`, UP `68.3227%`, DOWN `31.6773%` (n=2,033)

## Practical Notes
- Coverage vs accuracy is the tradeoff: larger `k` increases precision but reduces triggers.
- With 15m cadence there are 96 events/day.
  - Rough combined trigger rate (UP tail + DOWN tail) is about:
    - ~13-14% at `k=1.0` (≈ 13 predictions/day)
    - ~6.6-7.1% at `k=1.5` (≈ 6-7 predictions/day)
    - ~3.7-4.0% at `k=2.0` (≈ 3-4 predictions/day)

## Leakage / Timing Constraint
This feature uses `close@t0+1m` (1 minute after the candle starts).

- If we must bet strictly at `t0` (exactly at `:00/:15/:30/:45`), this is leakage.
- If we’re allowed to bet at `t0+1m` (e.g. `:01/:16/:31/:46`) for an event that resolves at `t0+15m`, it’s usable.

## Repro
- Training scan script (single-boundary scan + deciles/thresholds):
  - `scripts/window_edge/analyze_57open_to_01close_vs_00to14.py`
  - Output run used: `scripts/output/window_edge/20260210T201643Z/REPORT.md`

- Indicators quick backtest for the extreme-tail thresholds (last 14 days):
  - `scripts/window_edge/simulate_indicators_last2w_57to01_filters.py`
  - Output run used: `scripts/output/window_edge_indicators/20260210T202256Z/REPORT.md`
