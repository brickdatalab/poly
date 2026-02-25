# Research Catalog

## Scope
Research scripts are exploratory and analytics-focused. They are not part of the live runtime path.

## Core Research Areas
1. `scripts/window_edge/`
- Window-edge studies and threshold exploration.

2. `scripts/codex_signals_playground/`
- Runtime sandbox and dashboard exploration.

3. `scripts/training_schema_review/`
- Training schema audits and report generation.

4. `scripts/btc_1h_baseline/`
- Baseline model training utilities.

5. `scripts/indicator_sigma_sweeps/`
- Indicator threshold sweeps and sensitivity analysis.

6. `scripts/synthetic_indicators/research/`
- Canonical dataset prep, leakage tests, rolling walkforward metrics.

7. `syn-final/scripts/backtest_*.py`
- Historical synthetic strategy backtests.

## Usage Rules
1. Research scripts must not be scheduled as production runtime jobs.
2. Research outputs must not be written into production runtime tables unless explicitly routed through an ops-reviewed pipeline.
3. Any script graduating to production must be reclassified as `runtime` or `ops`, documented, and tested.

## Typical Commands
1. `python3 scripts/window_edge/<script>.py`
2. `python3 scripts/training_schema_review/run_all.py`
3. `python3 scripts/indicator_sigma_sweeps/run_two_indicator_sweeps.py`

## Phase 2 Direction
Research scripts will be progressively consolidated under top-level `research/` with clear boundaries from runtime and ops lanes.
