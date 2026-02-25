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
- AI operator runbook: `/Users/vitolo/Desktop/projects/poly/utility-scripts/ohlcv/README.md`

8. `utility-scripts/market_context/check_market_context_health.py`
- Purpose: Verify `public.market_context` freshness + minute continuity.
- Command: `python3 utility-scripts/market_context/check_market_context_health.py --lookback-minutes 180 --tldr`
- Dependencies: `public.market_context`, `ops.pipeline_slo_config`.
- AI operator runbook: `/Users/vitolo/Desktop/projects/poly/utility-scripts/market_context/README.md`

9. `utility-scripts/order_book/check_order_book_snapshots_health.py`
- Purpose: Verify `public.order_book_snapshots` freshness + minute continuity.
- Command: `python3 utility-scripts/order_book/check_order_book_snapshots_health.py --lookback-minutes 180 --tldr`
- Dependencies: `public.order_book_snapshots`, `ops.pipeline_slo_config`.
- AI operator runbook: `/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/README.md`

10. `utility-scripts/open_interest/check_open_interest_health.py`
- Purpose: Verify `indicators.open_interest` freshness + 15m continuity.
- Command: `python3 utility-scripts/open_interest/check_open_interest_health.py --lookback-hours 72 --tldr`
- Dependencies: `indicators.open_interest`, `ops.pipeline_slo_config`.
- AI operator runbook: `/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/README.md`

11. `utility-scripts/indicators/check_indicator_master_health.py`
- Purpose: Unified indicator master health traffic-light (`GREEN|YELLOW|RED`) with per-indicator diagnostics.
- Command: `python3 utility-scripts/indicators/check_indicator_master_health.py --lookback-hours 24 --tldr`
- Dependencies: `ops.master_indicator_registry`, `ops.fn_indicator_master_health_snapshot(...)`.
- AI operator runbook: `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/README.md`

12. `utility-scripts/indicators/check_indicator_compute_latency.py`
- Purpose: Close-to-populate latency SLO checker for `indicators.indicator_values`.
- Command: `python3 utility-scripts/indicators/check_indicator_compute_latency.py --lookback-hours 24 --tldr`
- Dependencies: `ops.indicator_latency_slo_config`, `ops.fn_indicator_compute_latency_snapshot(...)`.
- AI operator runbook: `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/README.md`

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
