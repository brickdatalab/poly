# Indicator Utilities Runbook (AI Agent)

## Canonical Scripts
1. `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/check_indicator_master_health.py`
2. `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/check_indicator_compute_latency.py`

## Purpose
1. `check_indicator_master_health.py`: one traffic-light status for technical indicator readiness across OHLCV-derived indicators, order book indicators, open interest, and OI features.
2. `check_indicator_compute_latency.py`: close-to-populate latency SLO status for `indicators.indicator_values` (`p50/p95/p99/max` by pair/timeframe/config).

## How To Run
1. Master health TLDR:
```bash
cd /Users/vitolo/Desktop/projects/poly
python3 utility-scripts/indicators/check_indicator_master_health.py --lookback-hours 24 --tldr
```
2. Latency TLDR:
```bash
python3 utility-scripts/indicators/check_indicator_compute_latency.py --lookback-hours 24 --tldr
```

## Verification (Required)
1. Contract tests:
```bash
pytest -q tests/ops/test_indicator_master_health_contracts.py tests/ops/test_indicator_latency_contracts.py
```

## Output Artifacts
All outputs are written to:
`/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/output/`

Patterns:
1. `indicator_master_health_<N>h_<UTCSTAMP>.json`
2. `indicator_compute_latency_<N>h_<UTCSTAMP>.json`

## Exit Code Contract
1. `0` = no hard failures (`WARN` allowed).
2. `1` = at least one hard failure.

## Constraints
1. Read-only diagnostics for health/latency checks.
2. No websocket ingestion architecture or behavior changes.
