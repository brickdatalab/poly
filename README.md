# poly

Operational notes and scripts for the Supabase-backed crypto + market-context streamers.

## Scripts

All reusable scripts live in:

`/Users/vitolo/Desktop/projects/poly/scripts/`

Useful ones:

- Snapshot current ingestion/coverage:
  - `/Users/vitolo/Desktop/projects/poly/scripts/ops_snapshot_ohlcv_state.py`
- All-in-one healthcheck (streamers + candles + indicators):
  - `/Users/vitolo/Desktop/projects/poly/scripts/healthcheck_all.py`
- Missing-candle report (last 7 full UTC days; all timeframes):
  - `/Users/vitolo/Desktop/projects/poly/scripts/report_missing_ohlcv_lookback_7d.py`
- Export missing 1m candles (UTC minutes) by pair:
  - `/Users/vitolo/Desktop/projects/poly/scripts/export_missing_ohlcv_1m_minutes.py`
- Backfill `public.raw_trades` from Coinbase Exchange historical trades:
  - `/Users/vitolo/Desktop/projects/poly/scripts/backfill_raw_trades_from_coinbase.py`
- Polymarket copy-trading bot (source wallet mirroring):
  - runbook: `/Users/vitolo/Desktop/projects/poly/clone/docs/runbooks/polymarket-copytrade-setup.md`
  - module: `/Users/vitolo/Desktop/projects/poly/clone/scripts/polymarket_copytrade/main.py`

## Schema / DB Change Log

When we change *database schema objects* (functions, triggers, role config), we record it here.

| UTC Timestamp | Change | Why | Rollback |
|---|---|---|---|
| 2026-02-08 03:35:00Z | `ALTER ROLE authenticator SET pgrst.db_schemas='public,graphql_public,polymarket,indicators,training'` and `NOTIFY pgrst, 'reload config'` | Fix PostgREST schema-cache failure (`PGRST002` / HTTP 503) caused by non-existent schema `v5` being listed in `pgrst.db_schemas` | Re-add the previous value to `pgrst.db_schemas` (not recommended) |
| 2026-02-08 05:25:00Z | `CREATE OR REPLACE FUNCTION indicators.fn_backfill_ohlcv(...)` to fix `ohlcv_45m` bucket calculation | `ohlcv_45m` was being backfilled with incorrect bucket_times (misaligned rows) due to an incorrect 45m bucket expression in `fn_backfill_ohlcv` | Re-apply the prior function definition saved in `/Users/vitolo/Desktop/projects/poly/scripts/output/fn_backfill_ohlcv_current.sql` |
| 2026-02-08 05:26:00Z | Rebuilt `indicators.ohlcv_45m` from `indicators.ohlcv_1m` and deleted misaligned `ohlcv_45m` rows | Clean up existing incorrect `ohlcv_45m` rows so rollups are aligned and consistent | Re-run the rebuild SQL (preferred) rather than restoring misaligned historical data |
