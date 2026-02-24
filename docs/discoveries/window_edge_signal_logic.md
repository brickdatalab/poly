# Window-Edge Signal (Natural Language Logic)

This documents the logic implemented in:

- `/Users/vitolo/Desktop/projects/poly/scripts/window_edge/window_edge_signal.py`

## Goal

At a 15-minute boundary (a candle start at `:00`, `:15`, `:30`, or `:45`), detect whether there is unusually strong boundary momentum in the 4-minute window spanning the boundary.

If it’s unusually strong **up**, we flag/predict **UP** for the 15-minute candle.
If it’s unusually strong **down**, we flag/predict **DOWN** for the 15-minute candle.

Pairs supported: `BTC-USD`, `ETH-USD`.

## Inputs (What Data It Reads)

From the serving/indicators database:

- `indicators.ohlcv_1m`

It needs two 1-minute candles relative to the event start time `t0`:

1. The **pre** candle at `t0 - 3 minutes` (we use its **open**)
2. The **post** candle at `t0 + 1 minute` (we use its **close**)

If either of those candles is missing, the signal returns `status = "missing_1m_candles_for_window"`.

## Event Time (`t0`)

`t0` is the 15-minute candle start time.

- If you pass `--t0`, the script uses that exact timestamp.
- If you do not pass `--t0`, the script uses the current time floored to the last quarter-hour boundary.

## Feature Computation

It computes one feature:

`pct_diff = ((close@t0+1m - open@t0-3m) / open@t0-3m) * 100`

Interpretation:

- Positive means price increased across the boundary window.
- Negative means price decreased across the boundary window.
- The value is a percent move (e.g. `0.22` means `+0.22%`).

## Hard Threshold Ladder (Frozen From Training)

The script does not compute sigma/mean/std on the fly.

Instead, it uses **hard, frozen thresholds** (and their expected accuracies) derived from training-schema analysis.
These thresholds are stored in `THRESHOLDS` inside the script.

There are two ladders per pair:

1. **UP ladder**: trigger if `pct_diff > +threshold_pct` and predict `UP`
2. **DOWN ladder**: trigger if `pct_diff < threshold_pct` (threshold is negative) and predict `DOWN`

Sigma levels included:

- `0.25σ`, `0.5σ`, `0.75σ`, `1.0σ`, `1.5σ`, `2.0σ`, `3.0σ`, `4.0σ`

Each ladder point includes:

- `sigma`: the sigma label from training
- `threshold_pct`: the hard percent threshold
- `expected_accuracy_pct`: training precision when that threshold triggers
- `match_rate_pct`: how often it triggers in training

You can print the full hard table:

```bash
python3 /Users/vitolo/Desktop/projects/poly/scripts/window_edge/window_edge_signal.py --pair BTC-USD --print-thresholds
python3 /Users/vitolo/Desktop/projects/poly/scripts/window_edge/window_edge_signal.py --pair ETH-USD --print-thresholds
```

## How the Script Decides “UP / DOWN / No Trigger”

1. Compute `pct_diff`.
2. Check which thresholds are passed.
   - For UP: all points where `pct_diff > threshold_pct`
   - For DOWN: all points where `pct_diff < threshold_pct`
3. Choose the **strongest** passed threshold.
   - “Strongest” means the highest `sigma` that still passes.
4. Emit the signal:
   - If an UP threshold passes: `prediction = "UP"`
   - Else if a DOWN threshold passes: `prediction = "DOWN"`
   - Else: `prediction = null` and `status = "no_trigger"`

The returned JSON includes:

- `passed_thresholds`: all thresholds passed (UP side and DOWN side)
- `signal`: the single chosen strongest threshold (the one you should act on)

## `min_sigma`

You can set a minimum sigma requirement.

Example:

- `--min-sigma 1.0` means “ignore 0.25σ/0.5σ/0.75σ triggers; only consider 1.0σ and above”.

## Output

The script prints a JSON payload to stdout.

Key fields:

- `feature.value`: the computed `pct_diff`
- `signal.prediction`: `UP` / `DOWN` / `null`
- `signal.sigma`: which sigma-level threshold triggered (if any)
- `signal.expected_accuracy_pct`: training-set precision for that threshold
- `status`: `ok`, `no_trigger`, or `missing_1m_candles_for_window`

## Timing / Leakage Constraint (Important)

This logic uses `close@t0+1m`, which is 1 minute after the boundary.

- If you must decide exactly at `t0`, this is not valid (future information).
- If you are allowed to decide at or after `t0+1m` for a market that resolves at `t0+15m`, it is valid.

