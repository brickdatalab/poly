# Realtime Recovery Runbook

## Purpose
Recover and verify the codex realtime signal pipeline when signals stop appearing due to upstream freshness gaps.

## Fast Triage
1. Capture snapshot:
`python3 scripts/synthetic_indicators/debug_snapshot_pipeline_state.py --out scripts/output/signal_pipeline_incident/snapshot.json`
2. Verify current stability gate:
`python3 scripts/synthetic_indicators/verify_realtime_stability_gate.py`

## Recovery
1. Dry run:
`python3 scripts/synthetic_indicators/recover_realtime_gap.py --dry-run`
2. Execute recovery:
`python3 scripts/synthetic_indicators/recover_realtime_gap.py --out scripts/output/signal_pipeline_incident/recovery.json`
3. Re-run stability gate:
`python3 scripts/synthetic_indicators/verify_realtime_stability_gate.py`

## Expected State After Recovery
1. `raw_trades` lag <= 90s for BTC/ETH/SOL.
2. `ohlcv_1m` lag <= 120s.
3. `indicator_values` lag <= 180s.
4. For each pair/window in last 2h, at least one of:
- `indicators.codex_signals` row exists
- `indicators.codex_signal_runtime_audit` row exists with reason (`no_signal` or `stale_inputs`)

## Notes
1. Recovery script is safe and idempotent over overlapping windows.
2. Recovery does not alter codex rule thresholds or prediction logic.
