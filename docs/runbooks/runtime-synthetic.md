# Runtime Synthetic Runbook

## Canonical Runtime Entry Points
1. Engine:
- `python3 runtime/synthetic/engine.py --pairs BTC-USD ETH-USD`

2. Signal producer runner:
- `python3 runtime/synthetic/run_all_signal_producers.py`

3. Launchpad server:
- `python3 runtime/launchpad/server.py`

4. Window scripts:
- `python3 runtime/synthetic/window/t2_window_up_signal.py`
- `python3 runtime/synthetic/window/t2_window_down_signal.py`

## Compatibility Entry Points (Legacy)
These remain available in Phase 1 and forward to canonical runtime modules:

1. `python3 syn-final/scripts/engine.py`
2. `python3 syn-final/scripts/run_all_signal_producers.py`

## Configuration
Load from repository `.env`:
1. `SUPABASE_DB_URL` or (`SUPABASE_URL` + `SUPABASE_DB_PASSWORD`)
2. Optional pool controls:
- `SUPABASE_POOL_MODE`
- `SUPABASE_POOLER_PORT`

## Freshness Contract
Runtime must fail closed when required dependencies are stale:
1. Required inputs missing/stale -> indicator status `not_ready`
2. No stale data should produce `ready` decisions
3. Compatibility wrappers must not alter runtime behavior

## Verification
Run before merge/deploy:

1. Runtime tests:
- `pytest tests/runtime -q`

2. Ops guardrail tests:
- `pytest tests/ops -q`

3. Optional script syntax gate:
- `python3 -m py_compile runtime/launchpad/server.py runtime/synthetic/*.py runtime/synthetic/window/*.py`

## Incident Recovery Linkage
For stale runtime dependencies or missing candles:
1. Follow [indicator-pipeline-recovery.md](/Users/vitolo/Desktop/projects/poly/docs/runbooks/indicator-pipeline-recovery.md)
2. Confirm health against [incident-response-slo.md](/Users/vitolo/Desktop/projects/poly/docs/runbooks/incident-response-slo.md)
