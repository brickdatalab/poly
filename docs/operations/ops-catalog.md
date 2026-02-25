# Ops Catalog

## Scope
Operational scripts used for monitoring, recovery, backfill, diagnostics, and incident response.

## Primary Runbooks
1. [indicator-pipeline-recovery.md](/Users/vitolo/Desktop/projects/poly/docs/runbooks/indicator-pipeline-recovery.md)
2. [incident-response-slo.md](/Users/vitolo/Desktop/projects/poly/docs/runbooks/incident-response-slo.md)
3. [gitops-operating-model.md](/Users/vitolo/Desktop/projects/poly/docs/runbooks/gitops-operating-model.md)

## Core Ops Scripts
1. `scripts/healthcheck_all.py`
- Purpose: End-to-end freshness/coverage snapshot.
- Command: `python3 scripts/healthcheck_all.py`
- Dependencies: indicators freshness tables/views/functions.

2. `scripts/ops/recovery_snapshot.py`
- Purpose: Capture current pipeline recovery posture.
- Command: `python3 scripts/ops/recovery_snapshot.py`
- Dependencies: queue state + indicators freshness.

3. `scripts/ops/check_postgrest_required_schemas.py`
- Purpose: Verify required PostgREST schema config is present.
- Command: `python3 scripts/ops/check_postgrest_required_schemas.py`
- Dependencies: `authenticator` role setting `pgrst.db_schemas`.

4. `scripts/export_missing_ohlcv_1m_minutes.py`
- Purpose: Export missing 1m windows for repair windows.
- Command: `python3 scripts/export_missing_ohlcv_1m_minutes.py`
- Dependencies: `indicators.ohlcv_1m`.

5. `scripts/report_missing_ohlcv_lookback_7d.py`
- Purpose: Gap report across configured timeframes.
- Command: `python3 scripts/report_missing_ohlcv_lookback_7d.py`
- Dependencies: `indicators.ohlcv_*`.

6. `scripts/backfill_raw_trades_from_coinbase.py`
- Purpose: Backfill source raw trades prior to OHLCV rebuild.
- Command: `python3 scripts/backfill_raw_trades_from_coinbase.py --help`
- Dependencies: Coinbase trade history + `public.raw_trades`.

7. `utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py`
- Purpose: Verify OHLCV sequential/completeness integrity (`1m..12h`) for last `N` days.
- Command: `python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr`
- Dependencies: `indicators.ohlcv_1m/5m/10m/15m/30m/45m/1h/2h/6h/12h`.

## Synthetic Diagnostics (Ops)
1. `scripts/synthetic_indicators/debug_snapshot_pipeline_state.py`
2. `scripts/synthetic_indicators/recover_realtime_gap.py`
3. `scripts/synthetic_indicators/repair_ohlcv_gaps_from_coinbase.py`
4. `scripts/synthetic_indicators/repair_ohlcv_missing_buckets.py`
5. `syn-final/scripts/check_inputs_*.py`

These are incident tools and validation checks, not runtime production entrypoints.

## Runtime Adjacency Rule
Ops scripts may touch runtime data, but they must:
1. run in bounded windows,
2. log actions and outcomes,
3. avoid changing websocket ingestion behavior,
4. preserve fail-closed semantics for stale dependencies.

## Phase 2 Direction
Operational scripts will be progressively moved under top-level `ops/` with compatibility wrappers retained until consumers are cut over.
