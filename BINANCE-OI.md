# Binance Open Interest Integration Recap (as of 2026-02-04)

## Goal
Implement a separate Binance Futures Open Interest (OI) pipeline for `BTC-USD`, `ETH-USD`, and `SOL-USD` that:
- runs on 15m cadence,
- stores data in a new `indicators.open_interest` table,
- computes model features (`oi_change`, `oi_volume_ratio`, `oi_divergence`),
- aligns exactly to local `indicators.ohlcv_15m` UTC buckets.

---

## What Was Researched

### Binance endpoints used
- Real-time OI: `/fapi/v1/openInterest`
- Historical OI (15m): `/futures/data/openInterestHist`

### Key design conclusions
- Keep OI in a **separate table** (`indicators.open_interest`), not appended to existing OHLCV/indicator tables.
- Use local `indicators.ohlcv_15m` as the canonical candle anchor for `bucket_time` alignment.
- Store Binance event time as `source_time` for traceability.
- Keep pair naming aligned with existing schema (`BTC-USD`, `ETH-USD`, `SOL-USD`).

---

## What Was Implemented

## 1) New ingestion pipeline
Created/updated:
- `scripts/alpha_v4/open_interest.py`
- `scripts/run_open_interest.py`

Capabilities added:
- Real-time OI pull for BTC/ETH/SOL from Binance Futures.
- Candle anchor from local `indicators.ohlcv_15m` (UTC bucketed).
- Feature computation:
  - `oi_change`
  - `oi_change_pct`
  - `oi_volume_ratio`
  - `price_change_pct`
  - `weak_rally` (`price up + OI down`)
  - `weak_selloff` (`price down + OI up`)
  - `oi_divergence` (1 if weak rally/selloff condition hit)

## 2) Separate table and schema alignment
Table ensured:
- `indicators.open_interest`

Columns include:
- identifiers: `symbol`, `pair`, `binance_symbol`, `bucket_time`
- raw/derived OI fields and divergence features
- `source_time`, `ingested_at`

Indexes include:
- `bucket_time DESC`
- `(pair, bucket_time DESC)`

Migration safety behavior:
- `ensure_table()` creates table/indexes if missing.
- Backfills `pair` for existing rows if null.

## 3) API mode for scheduler-based execution
Added HTTP API server mode (no manual tick execution required):
- `GET /health`
- `POST /open-interest/tick`
- `POST /open-interest/backfill`

Security:
- `X-API-Key` via `OPEN_INTEREST_API_KEY`.

## 4) Backfill support
Added backfill engine:
- CLI mode: `--backfill-start` + `--backfill-end`
- API mode: `POST /open-interest/backfill` with JSON body containing `start`, `end`, and optional `symbols`.
- Aligns historical OI snapshots to 15m buckets and joins to local OHLCV buckets.

---

## Tests Added and Run

Test file:
- `scripts/tests/test_open_interest.py`

Coverage includes:
- OI payload parsing
- Historical payload parsing
- 15m bucket flooring logic
- feature math for weak rally/selloff divergence
- schema SQL shape validation
- API arg parsing
- OHLCV row-to-candle snapshot alignment

Latest result:
- `python -m unittest discover -s scripts/tests -p 'test_open_interest.py'`
- **8 tests passed**

---

## Credentials / Config Setup Done

Files updated:
- `.env` (workspace-local secrets)
- `.gitignore` updated to ignore `.env`

Configured in `.env`:
- `OPEN_INTEREST_API_KEY`
- Supabase URL/DB/service credentials (values not repeated here)

---

## Live Execution Attempts and Findings

## 1) DB connectivity
- Supabase DB connection check succeeded.

## 2) 3-day backfill test (requested validation run)
Attempted for:
- `BTC-USD`, `ETH-USD`, `SOL-USD`
- window: `2026-02-01T13:30:00Z` to `2026-02-04T13:30:00Z`

Result:
- Binance Futures API returned **HTTP 451** from current network.
- No OI rows ingested (external data source blocked from this runtime location).

## 3) Alignment baseline check
For same 3-day window:
- `ohlcv_rows` per pair: `289`
- `oi_rows` per pair: `0`
- `missing_in_oi`: `289` each pair

Interpretation:
- Local candle coverage exists and alignment queries work.
- Ingestion is blocked by network/regional access to Binance Futures endpoint from this environment.

---

## Current Status

- Pipeline code is implemented and tested.
- Separate table strategy is in place.
- Pair naming now matches existing tables.
- API scheduler mode is implemented.
- Backfill mechanism is implemented.
- Current blocker: Binance Futures endpoint access (`HTTP 451`) from current network.

---

## Recommended Next Step Before Full Rollout

Run the same 3-day backfill from a network/location that can access Binance Futures, then re-run alignment check:
- matched buckets vs `indicators.ohlcv_15m` by `(pair, bucket_time)`,
- confirm no drift,
- then proceed with max backfill and recurring scheduler execution.

