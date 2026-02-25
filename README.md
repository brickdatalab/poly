# poly

Supabase-backed crypto market-data and indicator runtime.

## Repository Lanes

1. `runtime/`
- Canonical live synthetic runtime path.
- Includes launchpad/dev server and window scripts.

2. `supabase/`
- Migrations, Edge Functions, and db config.

3. `scripts/`
- Existing ops and research script namespaces (Phase 1 retained).

4. `docs/`
- Plans, runbooks, architecture, and incident artifacts.

## Runtime Entry Points

1. `python3 runtime/synthetic/engine.py --pairs BTC-USD ETH-USD`
2. `python3 runtime/synthetic/run_all_signal_producers.py`
3. `python3 runtime/launchpad/server.py`

Compatibility wrappers remain available:
1. `python3 syn-final/scripts/engine.py`
2. `python3 syn-final/scripts/run_all_signal_producers.py`

## Script Classification Policy

All executable scripts must be classified as one of:
1. `runtime`
2. `ops`
3. `research`
4. `archive`

Source of truth:
1. `docs/architecture/repo-script-classification.md`
2. `docs/architecture/repo-script-inventory.csv`
3. `docs/operations/ops-catalog.md`
4. `docs/research/research-catalog.md`

## Reliability Runbooks

1. `docs/runbooks/runtime-synthetic.md`
2. `docs/runbooks/indicator-pipeline-recovery.md`
3. `docs/runbooks/incident-response-slo.md`
4. `docs/runbooks/gitops-operating-model.md`

## Common Ops Scripts

1. `python3 scripts/healthcheck_all.py`
2. `python3 scripts/ops/recovery_snapshot.py`
3. `python3 scripts/export_missing_ohlcv_1m_minutes.py`
4. `python3 scripts/report_missing_ohlcv_lookback_7d.py`
5. `python3 scripts/backfill_raw_trades_from_coinbase.py --help`

## Data Integrity Constraint

Websocket ingestion behavior from the GCP VM is out of scope for repo-organization work and must not be changed on this track.

## Schema / DB Change Log

When we change *database schema objects* (functions, triggers, role config), we record it here.

| UTC Timestamp | Change | Why | Rollback |
|---|---|---|---|
| 2026-02-08 03:35:00Z | `ALTER ROLE authenticator SET pgrst.db_schemas='public,graphql_public,polymarket,indicators,training'` and `NOTIFY pgrst, 'reload config'` | Fix PostgREST schema-cache failure (`PGRST002` / HTTP 503) caused by non-existent schema `v5` being listed in `pgrst.db_schemas` | Re-add the previous value to `pgrst.db_schemas` (not recommended) |
| 2026-02-08 05:25:00Z | `CREATE OR REPLACE FUNCTION indicators.fn_backfill_ohlcv(...)` to fix `ohlcv_45m` bucket calculation | `ohlcv_45m` was being backfilled with incorrect bucket_times (misaligned rows) due to an incorrect 45m bucket expression in `fn_backfill_ohlcv` | Re-apply the prior function definition saved in `/Users/vitolo/Desktop/projects/poly/scripts/output/fn_backfill_ohlcv_current.sql` |
| 2026-02-08 05:26:00Z | Rebuilt `indicators.ohlcv_45m` from `indicators.ohlcv_1m` and deleted misaligned `ohlcv_45m` rows | Clean up existing incorrect `ohlcv_45m` rows so rollups are aligned and consistent | Re-run the rebuild SQL (preferred) rather than restoring misaligned historical data |

## Reliability Runbooks

- Pipeline recovery decision tree:
  - `/Users/vitolo/Desktop/projects/poly/docs/runbooks/indicator-pipeline-recovery.md`
- GitOps operating model:
  - `/Users/vitolo/Desktop/projects/poly/docs/runbooks/gitops-operating-model.md`
- Incident SLOs:
  - `/Users/vitolo/Desktop/projects/poly/docs/runbooks/incident-response-slo.md`
