# Base Project Analysis — Polymarket Crypto Prediction Bot
**Updated**: February 10, 2026  
**Original Baseline**: February 6, 2026  
**Project**: `poly` (Supabase project-ref `cxvntzszdkyggjjenefn`) — Supabase Postgres `17.6.1` (AWS `us-east-2`)
**Schemas Analyzed**: `public`, `indicators`, `training`, `polymarket`, `alpha`, `mining`

---

## Executive Summary

This is a **15-minute crypto price prediction system** with a live ingestion + indicators pipeline and a separate historical training layer.

```
public (raw ingestion) → indicators (real-time computation) → [models/prediction consumers]
                                      ↘ training (historical ML feature engineering)
polymarket (live market snapshots)     alpha (feature store + predictions)
```

**Current state (as of Feb 10, 2026)**:
- **Live ingestion is running**: `public.ohlcv_1m` is current through **2026-02-10 00:44Z** (BTC/ETH/SOL) and `indicators.ohlcv_1m` is current through **2026-02-10 00:45Z** (BTC/ETH/SOL). `indicators.v_model_15m` is currently populated through **2026-02-10 00:15Z**.
- **Indicators are running**: `indicators.indicator_values_*` contains ~**1.4M** long-form indicator rows across weekly partitions.
- **Training is partially ready**:
  - Historical track: `training.unified_15m` and `training.synthetic_features` are populated, but historical training data is **not current** past **2026-02-01**, and `training.feature_matrix` / `training.event_labels` remain empty.
  - RT-alignment track (new): `training` now contains an **indicators-compatible dataset** built by snapshotting `indicators.v_model_15m` and production labels from `public.price_intervals_15m_live` (see Section 3 and Section 9). This is the best-match dataset for models that will score on `indicators`.
- **Polymarket integration exists in two places**:
  - `polymarket.*` schema has live snapshot tables (`markets_live_15m`, `markets_live_1h`).
  - `training.polymarket_*` tables are still present but empty (reserved for training-time joins).

---

## Schema Overview

| Schema | Tables | Purpose | Status |
|--------|--------|---------|--------|
| **public** | 54 (+ 1 partitioned parent, + 3 views) | Raw trade ingestion + live interval state | Live, streaming |
| **indicators** | 47 (+ 1 partitioned parent, + 8 views) | Real-time OHLCV rollups + indicators + OI features | Live, 156 configs active |
| **training** | 19 (+ 1 partitioned parent, + 9 views) | Historical spot + enriched indicators + curated training sets + RT-aligned datasets | Operational for RT-aligned training; historical track through 2026-02-01 |
| **polymarket** | 2 | Live Polymarket market snapshot tables | Live |
| **alpha** | 8 (+ 4 views) | Feature store + predictions/signals tables | Partially operational (predictions stale since 2026-02-02) |
| **mining** | 7 | Offline mining / condition-stats tables | Active, but not in live ingestion path |

---

## Repo Layout / How To Run Things

This repository is an **ops + analysis workspace**, not the full application codebase:
- `/Users/vitolo/Desktop/projects/poly/scripts/`: Python 3.11 scripts used for healthchecks, coverage snapshots, backfills, and schema doc generation.
- `/Users/vitolo/Desktop/projects/poly/docs/plans/`: operational runbooks (notably the **2026-02-08 OHLCV ingestion outage** plan and backfill approach).
- `/Users/vitolo/Desktop/projects/poly/supabase/`: contains only Supabase CLI `.temp` metadata (project-ref, versions). **Migrations/functions are not tracked here**.

Quick commands (local):
- Healthcheck: `python3 /Users/vitolo/Desktop/projects/poly/scripts/healthcheck_all.py`
- OHLCV state snapshot: `python3 /Users/vitolo/Desktop/projects/poly/scripts/ops_snapshot_ohlcv_state.py`
- Missing-candle report: `python3 /Users/vitolo/Desktop/projects/poly/scripts/report_missing_ohlcv_lookback_7d.py`
- Backfill raw trades (Coinbase historical): `python3 /Users/vitolo/Desktop/projects/poly/scripts/backfill_raw_trades_from_coinbase.py`
- Compare training vs indicators (15m): `python3 /Users/vitolo/Desktop/projects/poly/scripts/compare_training_vs_indicators_15m.py`

Security note:
- `/Users/vitolo/Desktop/projects/poly/.env` contains Supabase credentials and an Open Interest API key. Treat it as sensitive and ensure it is excluded from any public sync.

---

## 1. PUBLIC Schema — Raw Data Ingestion Layer

### Purpose
Captures real-time trade data from Coinbase streams (BTC-USD, ETH-USD, SOL-USD) plus a small `TEST-USD` test pair, and maintains live interval state used by downstream systems.

### Table Groups (as of Feb 10, 2026)

**Raw Trade Data** (1 partitioned parent + **36** monthly partitions):
- `raw_trades` → partitions `raw_trades_YYYY_MM`
- Estimated live rows across partitions: **~36.3M** (from `pg_stat_user_tables.n_live_tup`)
- Example: `raw_trades_2026_01` has **~17.6M** rows
- Columns: `trade_id, pair, price, size, side, executed_at` (+ surrogate `id`)
- **Note**: Partitions lack primary keys (beyond the surrogate `id`) — duplicates remain possible if upstream replays aren’t deduped

**OHLCV Aggregation**:
- `ohlcv_1m` — **~99.6K** rows (Jan 15 – Feb 10, 2026)
- Columns: `pair, bucket_time, open, high, low, close, volume` (+ `created_at`)
- Note: buy/sell volume + trade counts live in `indicators.ohlcv_1m` (not `public.ohlcv_1m`)

**Order Book**:
- `order_book_snapshots` — JSONB bids/asks snapshots (~1s cadence)
- Columns: `pair, captured_at, bids (jsonb), asks (jsonb)`

**Market Context**:
- `market_context` — best bid/ask, spread data
- `trade_flow_snapshots` — 13 cols, aggregated trade flow metrics
- `price_intervals_15m_live` — live 15m interval state (current through **2026-02-09 19:45Z**)

**Prediction Tables**:
- `gpt52-predictions` (16 cols) — GPT-5.2 model predictions
- `sfm-predictions` (16 cols) — SFM model predictions (same schema, A/B testing)
- `gpt52-outcome-table` (12 cols) — prediction outcomes/accuracy
- `gpt52_calibration` (9 cols) — confidence-to-accuracy calibration mapping
- Note: these appear **stale** in current production data (latest `created_at` around **2026-02-02** for predictions; outcomes earlier)

**Smash Execution Engine**:
- `smash` (23 cols) — rule-based trade execution records
- `smash_sfm` (17 cols) — SFM variant execution
- `smash_metrics` (6 cols) — aggregated performance
- `smash_trigger_log` (4 cols) — execution trigger audit
- Note: recent activity appears limited (latest `created_at` in `smash_sfm` around **2026-02-01**)

**Config & Operational**:
- `base_config` (7 cols) — model parameters as JSONB
- `websocket_heartbeat` (8 cols, 1 row) — stream health singleton
- `all_readme` (7 cols) — documentation registry

### Key Issues — Public Schema
- **Hyphenated table names** (`gpt52-predictions`, `sfm-predictions`) require SQL quoting — recommend rename to snake_case
- **No PKs on raw_trade partitions** — duplicate risk
- **Legacy `public.indicators` table** (11 cols) overlaps with `indicators` schema — likely deprecated
- **RLS disabled** on all tables

---

## 2. INDICATORS Schema — Real-Time Computation Layer

### Purpose
Transforms raw OHLCV data into 156 technical indicator configurations across 39 unique indicators and 6 categories. Designed as a standalone computation layer that reads from `public` without modifying source data.

### Architecture Decisions

1. **Flat/Long table design** — `indicator_values` stores `(pair, bucket_time, config_id, v1-v5)` instead of 780+ wide columns
2. **10 separate OHLCV tables** — one per timeframe (1m through 12h) for query isolation
3. **Weekly partitioning** on `indicator_values` — **29** partitions currently present (w2026_03 through w2026_31, most future partitions empty)
4. **Config-driven** — `indicator_configs` table defines all computation rules via JSONB params
5. **Async job queue** — computation decoupled from INSERT triggers after synchronous blocking incident

### Data Flow

```
public.raw_trades
    ↓ (trigger/worker)
indicators.ohlcv_1m (~80.5K rows)
    ↓ (fn_rollup_ohlcv)
indicators.ohlcv_5m/10m/15m/30m/45m/1h/2h/6h/12h
    ↓ (fn_compute_all_indicators, orchestrator)
indicators.indicator_values (~1.40M rows across weekly partitions)
    ↓ (logged)
indicators.computation_log (~14.1K entries)
```

### Objects (as of Feb 10, 2026)
- Tables: **47** (+ `indicator_values` partitioned parent)
- Views: **8** (including `v_model_15m`, `v_model_1h`, etc.)
- Functions: **55**

**OHLCV Tables (10)**:
| Table | Timeframe | Key Use |
|-------|-----------|---------|
| ohlcv_1m | 1 min | Base aggregation, fast indicators |
| ohlcv_5m | 5 min | Short-term analysis |
| ohlcv_15m | 15 min | **PRIMARY** — matches Polymarket timeframe |
| ohlcv_1h | 1 hour | Trend context |
| + 6 more | 10m,30m,45m,2h,6h,12h | Extended timeframes |

Common columns: `id, pair, bucket_time, open, high, low, close, volume, buy_volume, sell_volume, trade_count, created_at`

**Indicator Values (1 parent + 29 partitions)**:
- Parent: `indicator_values` — ~**1.40M** rows across partitions (data present at least through week `w2026_06`)
- Partitions: `w2026_03` through `w2026_31` (most future partitions are currently empty)
- Schema: `id, pair, bucket_time, config_id, v1, v2, v3, v4, v5, created_at`

**Indicator Configs (156 active)**:

| Category | Count | Indicators |
|----------|-------|-----------|
| moving_average | 37 | ema, hma, sma, vwma, wma |
| oscillator | 33 | cci, mfi, momentum, roc, rsi, stoch_rsi, stochastic, williams_r |
| volume | 28 | adl, bop, cmf, cvd, eom, force_index, obv, pvt, vwap |
| trend | 22 | adx, aroon, macd, parabolic_sar, supertrend, vortex |
| volatility | 21 | atr, bollinger, donchian, keltner, rvi, ulcer_index |
| complex | 15 | awesome_oscillator, ichimoku, linear_regression, pivot_points, ultimate_oscillator |

**Timeframe Distribution**:
| Timeframe | Configs | Indicators | Primary Use |
|-----------|---------|------------|-------------|
| 1m | 11 | 6 | Scalping, noise filtering |
| 5m | 34 | 23 | Short-term momentum |
| 15m | 62 | 39 | **PRIMARY — Polymarket predictions** |
| 30m | 2 | 2 | RSI + MACD confirmation |
| 1h | 46 | 38 | Trend context |
| 2h | 1 | 1 | Pivot points |

**55 Postgres Functions**:
- Dozens of individual indicator functions (fn_compute_rsi, fn_compute_macd, etc.)
- 1 orchestrator: `fn_compute_all_indicators`
- 1 OHLCV rollup: `fn_backfill_ohlcv`
- 3 real-time: `fn_process_new_trade`, `fn_cascade_timeframes`, `fn_rollup_ohlcv`
- Health check: `fn_health_check`

**Order Book Indicators** (~150.4K rows, Jan 15 – Feb 10):
- Columns: `depth_ratio, imbalance, spread_pct, mid_price, bid/ask_depth_10/25/50bps, bid/ask_slope, slippage_buy/sell_100/1000`

**Operational Tables**:
- `computation_log` (~14.1K rows) — tracks status, execution_ms, triggered_by
- `job_queue` (8 cols) — async computation queue with SKIP LOCKED
- `readme` — living documentation table

### Key Issues — Indicators Schema
- `temp-table1` (wide table) appears to be a scratch / transitional feature-matrix table; it is populated and should either be formalized (moved to a dedicated schema) or removed
- `open_interest` is now populated (and `oi_features` exists), but the pipeline should be treated as **experimental** until it is validated against downstream expectations
- `indicator_values_*` partitions now include an FK to `indicator_configs(config_id)`, but this constraint is defined per-partition (verify parent-table expectations before relying on it in tooling)
- Several key `indicators.*` views are defined as **SECURITY DEFINER** (shows up in Supabase DB lints); this is powerful but increases blast radius if any view logic is unsafe
- RLS disabled on all tables

### Critical Incident Record
- **Jan 25, 2026**: Synchronous trigger blocked all trade inserts (~200-500ms per trade computation). Resolved by switching to async job queue + Edge Function worker pattern. Lesson: never put expensive computation in INSERT triggers.

---

## 3. TRAINING Schema — Historical ML Feature Engineering

### Purpose
Historical data archive (6+ years) with progressively enriched technical indicators, culminating in ML-ready feature matrices for training price prediction models.

### Feature Pipeline

```
spot_1m (4.5M rows, 2017-2025)
    ↓ aggregation
spot_15m (634K rows) / spot_1h (159K rows) — since 2019
    ↓ 104 indicators computed
spot_15m_indicators / spot_1h_indicators — 104 cols each
    ↓ unification + feature selection
unified_15m (77 cols, 634K rows) / unified_1h (76 cols, 159K rows)
    ↓ pattern detection
synthetic_features (35 cols, 154K rows) — since 2020
    ↓ [NOT YET IMPLEMENTED]
feature_matrix (59 cols, 0 rows) + event_labels (0 rows)

--- RT-alignment track (added 2026-02-09 UTC) ---

indicators.v_model_15m (serving features)
    ↓ snapshot (training-owned table; refreshable)
training.rt_features_from_indicators_15m_v1
public.price_intervals_15m_live (production outcomes)
    ↓ snapshot (training-owned table; refreshable)
training.rt_labels_from_public_15m_v1
    ↓ join + gating
training.v_rt_dataset_from_indicators_15m_scoreable_current (recommended)
```

### Objects (as of Feb 10, 2026)
- Tables: **19** (+ `polymarket_ticks` partitioned parent)
- Views: **9**
- Functions: **1** (`training.refresh_rt_features_from_indicators_15m_v1()`)

**Spot Price Data** (3 tables, 5.3M rows):

| Table | Rows | Range | PK | Timestamp Col |
|-------|------|-------|----|----|
| spot_1m | 4,557,646 | 2017-08 → 2025-03 | (symbol, ts) | `ts` |
| spot_15m | 633,984 | 2019-09 → 2026-02 | (symbol, open_time) | `open_time` |
| spot_1h | 158,506 | 2019-09 → 2026-02 | (symbol, open_time) | `open_time` |

- `spot_1m` has 24 cols including built-in indicators (ma_20/50/200, rsi, macd, bb_*, stoch_*, adx, atr, obv, vwap, trendlines)
- `spot_15m/1h` have 18 cols: OHLCV + derived metrics (pct_change, high_low_range, wick percentages)

**Indicator Enrichment** (2 tables, 793K rows):
- `spot_15m_indicators` — 104 columns of technical indicators
- `spot_1h_indicators` — 104 columns (same structure)
- Covers: 16 moving averages, 21 oscillators, 17 trend, 13 volatility, 28 volume, 5 complex

**Polymarket Data** (5 tables, ALL EMPTY):
- `polymarket_ticks` (26 cols) — tick-level order book snapshots
- `polymarket_ticks_btc/eth/sol` (26 cols each) — per-asset variants
- `polymarket_oracle` (17 cols) — aggregated oracle prices
- `polymarket_15m_agg` (16 cols) — windowed aggregations

**Feature Engineering** (2 tables):
- `synthetic_features` (35 cols, 153,730 rows) — pattern detection:
  - Supertrend confirmations, VWAP rejections, BB breakouts
  - Ichimoku setups, MACD acceleration
  - Squeeze detection (Bollinger/Keltner)
  - Trend regime classification (bull/bear/weak)
  - CMF/CVD volume-price confluence
  - Forward labels (next_label, next_pct_change)
- `feature_matrix` (59 cols, **0 rows** — not yet populated):
  - Returns at 5 timeframes, normalized momentum, trend, volatility
  - Cross-asset features (BTC/ETH/SOL correlations)
  - Temporal encodings (hour/dow sin/cos)
  - Polymarket features (pm_prob_up, pm_spread, pm_imbalance)
  - Order flow (trades count, taker buy ratio)

**Unified Views** (2 tables, 792K rows):
- `unified_15m` (77 cols) — curated ~50 of 104 available indicators + synthetic signals + labels
- `unified_1h` (76 cols) — same structure for hourly

**Labels** (1 table, **0 rows**):
- `event_labels` — symbol, window_type, window_start, open/close prices, price_change, pct_change, label

### RT-Alignment Layer (v1, additive-only)

This layer exists specifically to reduce training-serving skew when scoring models on `indicators` without changing `indicators`.

**Core objects**
- `training.rt_ohlcv_15m_v1` (view): RT-style candle naming derived from `training.spot_15m` (pair/bucket_time + buy/sell volume + trade_count).
- `training.rt_labels_15m_v1` (table): labels computed from `training.spot_15m` using **boundary open → next boundary open** semantics (mirrors how `public.price_intervals_15m_live` is computed).
- `training.rt_features_from_indicators_15m_v1` (table): snapshot of `indicators.v_model_15m` (serving features) stored in `training`.
- `training.rt_labels_from_public_15m_v1` (table): snapshot of production labels from `public.price_intervals_15m_live` stored in `training`.
- `training.refresh_rt_features_from_indicators_15m_v1()` (function): refreshes both snapshot tables (TRUNCATE + INSERT).

**Canonical dataset (recommended for models that will score on indicators)**
- `training.v_rt_dataset_from_indicators_15m_scoreable_current` (view): joins serving-feature snapshots to production labels and filters to rows where the 33 v1 feature columns + outcome are non-null.

**Current snapshot state (point-in-time)**
- `training.rt_features_from_indicators_15m_v1`: 5,364 rows, `2026-01-22 07:00Z` → `2026-02-09 22:30Z` (requires refresh to stay current).
- `training.v_rt_dataset_from_indicators_15m_scoreable_current`: 3,932 rows, `2026-01-25 02:45Z` → `2026-02-09 22:30Z`.

### Key Issues — Training Schema
- **Inconsistent timestamp naming**: `ts` (spot_1m) vs `open_time` (spot_15m) vs `ts` as int8 (polymarket_ticks)
- **All Polymarket tables empty** — integration planned but not implemented
- **feature_matrix and event_labels empty** — final training pipeline not operational
- **spot_1m stale** — last updated 2025-03, not current
- **No PKs on polymarket_ticks** — duplicate risk
- **float8 vs numeric** — training uses float8, indicators uses numeric (type mismatch on joins)
- **104-column indicator tables** — very wide, could benefit from partitioning by symbol

### ML Readiness: 60%
**What works now**:
- Historical training: can train models using `training.v_rt_dataset_15m_from_unified_scoreable_current` (long history, but not identical to realtime serving semantics).
- Best-match for production scoring: can train/calibrate using `training.v_rt_dataset_from_indicators_15m_scoreable_current` (features identical to serving view; point-in-time snapshot that must be refreshed).

**What's still missing**:
- Polymarket training-time feature ingestion (`training.polymarket_*` remains empty)
- `training.feature_matrix` and `training.event_labels` population (the “single canonical historical table” pipeline)

**Estimated gap**: depends on whether you accept the indicators-snapshot dataset as the production training set.

---

## 4. Cross-Schema Data Flow

```
                    COINBASE WEBSOCKET
                          │
                          ▼
               public.raw_trades (~36M est)
              ┌───────────┼───────────┐
              ▼           ▼           ▼
      public.ohlcv_1m  order_book  market_context
        (~99K rows)   snapshots    (~31.8M rows)
              │
              ▼
    indicators.ohlcv_1m → 5m → 15m → 1h → ... → 12h
              │
              ▼
    indicators.indicator_values (~1.40M rows)
    156 configs × 3 pairs × rolling window
              │
              ├──────────────────────────────┬──────────────────────────┐
              ▼                              ▼                          ▼
    public.price_intervals_15m_live   training.spot_15m/1h              polymarket.markets_live_15m/1h
    (live interval state)             → spot_*_indicators (104 cols)     (live market snapshots)
                                     → unified_15m/1h (77 cols)
                                     → synthetic_features (35 cols)
                                     → feature_matrix (planned, empty)

    alpha.features_* (feature store) + alpha.predictions_* (stale since 2026-02-02)

     training.rt_features_from_indicators_15m_v1 (snapshot of indicators.v_model_15m)
     + training.rt_labels_from_public_15m_v1 (snapshot of public.price_intervals_15m_live)
        → training.v_rt_dataset_from_indicators_15m_scoreable_current (recommended)
```

---

## 5. Key Numbers at a Glance

| Metric | Value |
|--------|-------|
| Active pairs | BTC-USD, ETH-USD, SOL-USD (+ `TEST-USD` for limited testing) |
| Raw trades (total) | ~36.3M est rows across monthly partitions |
| Raw trades/day | ~0.55M/day (rough, based on Jan 2026 partition scale) |
| OHLCV 1m rows (public) | ~99.6K |
| OHLCV 1m rows (indicators) | ~80.5K |
| Active indicator configs | 156 (39 unique indicators) |
| Indicator values (live) | ~1.40M rows (weekly partitions) |
| Order book indicator rows | ~150.4K |
| Open interest rows (indicators.open_interest) | ~6.0K |
| OI feature rows (indicators.oi_features) | ~5.2K |
| Polymarket live snapshots | markets_live_15m: 3,576 rows; markets_live_1h: 123 rows |
| Historical spot data (training) | ~4.56M rows (1m), 633,984 (15m), 158,506 (1h) |
| Historical range | 2017-08-18 to 2026-02-01 (but spot_1m ends 2025-03-19) |
| Training indicators | 104 columns per timeframe |
| Synthetic features | 35 pattern signals |
| RT-aligned dataset (best match) | `training.rt_features_from_indicators_15m_v1`: 5,364 rows; scoreable join view: 3,932 rows (point-in-time snapshot) |
| Weekly partitions (indicator_values) | 29 (w2026_03 → w2026_31; most future empty) |
| Monthly partitions (raw_trades) | 36 (raw_trades_YYYY_MM) |
| Postgres functions | indicators: 55; public: 38 |
| Primary prediction timeframe | 15 minutes |

---

## 6. Known Issues & Technical Debt

### High Priority
1. **Hyphenated table names** in public (`gpt52-predictions`, `sfm-predictions`) — requires quoting everywhere
2. **No PKs on raw_trade partitions** — allows duplicate inserts
3. **Training pipeline incomplete** — `training.feature_matrix` and `training.event_labels` are empty (blocks a clean “single table” training dataset)
4. **Training Polymarket tables empty** — `training.polymarket_*` remains unpopulated, so training-time “market probability / liquidity” features aren’t available yet
5. **RLS disabled across all analyzed schemas** — acceptable for private/internal pipelines, but high risk if any tables are exposed via PostgREST/GraphQL
6. **Edge Functions mostly `verify_jwt=false`** — convenient for internal workers, but dangerous if any endpoint is publicly reachable without additional auth controls

### Medium Priority
7. **Inconsistent timestamp columns** — `ts` vs `open_time` vs `bucket_time` across schemas
8. **`indicator_values` FK is per-partition** — constraints exist on `indicator_values_w*`, but tooling should not assume the partitioned parent enforces it
9. **Legacy `public.indicators` table** — overlaps with `indicators` schema, likely deprecated
10. **spot_1m stale** — last updated 2025-03-19, not current
11. **`indicators.temp-table1`** — populated scratch/transitional table; should be formalized or removed
12. **SECURITY DEFINER views and mutable `search_path`** — flagged by Supabase DB lints; tighten `search_path` and review view definitions for safety
13. **RT-aligned indicators snapshot requires refresh** — `training.rt_features_from_indicators_15m_v1` is point-in-time and must be refreshed via `training.refresh_rt_features_from_indicators_15m_v1()` to stay current

### Low Priority
14. **Wide tables (104+ cols)** in training — could benefit from symbol-based partitioning if query patterns demand it
15. **Duplicate / unused indexes** — Supabase performance lints flag several duplicate indexes and many unused indexes (likely acceptable while patterns stabilize)

---

## 7. Architecture Patterns Reference

### Pattern: Config-Driven Indicators
```sql
-- Add new indicator: just insert a config row
INSERT INTO indicators.indicator_configs (config_id, indicator_name, category, timeframe, params, output_columns)
VALUES ('rsi_7_5m', 'rsi', 'oscillator', '5m', '{"period": 7}', '{"v1": "value"}');

-- Query latest 15m indicators for ETH
SELECT config_id, v1, v2, v3, v4, v5
FROM indicators.indicator_values
WHERE pair = 'ETH-USD'
  AND bucket_time = (SELECT MAX(bucket_time) FROM indicators.indicator_values WHERE pair = 'ETH-USD')
  AND config_id IN (SELECT config_id FROM indicators.indicator_configs WHERE timeframe = '15m');
```

### Pattern: Async Job Queue (post-incident)
```
Trade INSERT → Trigger (fast: ~2-3ms)
    → UPSERT ohlcv_1m
    → INSERT job_queue (when bucket closes)
    → pg_notify('indicator_jobs')
        → Edge Function Worker
            → fn_rollup_ohlcv (if timeframe != 1m)
            → fn_compute_all_indicators
            → indicator_values table
Total latency: 220-520ms, non-blocking
```

### Pattern: Weekly Partition Management
```sql
-- Create new partition
CREATE TABLE indicators.indicator_values_w2027_07
PARTITION OF indicators.indicator_values
FOR VALUES FROM ('2027-02-10') TO ('2027-02-17');

-- Drop old partition
DROP TABLE indicators.indicator_values_w2026_03;
```

### Pattern: Indicator Value Ranges (Validation)
| Indicator | Valid Range | Bug Signal |
|-----------|-------------|-----------|
| RSI, MFI, Stoch, ADX | 0-100 | Values outside |
| Williams %R | -100 to 0 | Values outside |
| CMF, BOP | -1 to +1 | Values outside |
| R-Squared | 0-1 | Values outside |
| SuperTrend direction | -1 or 1 | Other values |
| Price-based (SMA, VWAP, etc.) | Near current price | >50% deviation |

---

## 8. Supabase Buildout Snapshot (Feb 10, 2026)

### Project / Platform
- Project URL: `https://cxvntzszdkyggjjenefn.supabase.co`
- Postgres: `17.6.1` (Supabase reports `17.6.1.063`)
- Region: pooler hostname indicates AWS `aws-1-us-east-2`
- Storage buckets: none configured
- Supabase branches: none

### Edge Functions (ACTIVE)
- `rubric-v6-eval` (verify_jwt=true)
- `indicator-worker` (verify_jwt=false)
- `predict-crypto` (verify_jwt=false)
- `predict-gemini` (verify_jwt=false)
- `gemini-payload` (verify_jwt=false)
- `polymarket-execute` (verify_jwt=false)
- `polymarket-populate-markets` (verify_jwt=false)
- `populate-tokens` (verify_jwt=false)
- `test-gamma` (verify_jwt=false)

Operational note: treat any `verify_jwt=false` function as public unless you have compensating controls (network restrictions, custom auth, allowlists, secrets, etc.).

### Recent DB Changes (from migration history + local ops notes)
- **2026-02-08**: removed non-existent schema `v5` from PostgREST schema cache config (resolving `PGRST002` / 503 issues); see `/Users/vitolo/Desktop/projects/poly/README.md`
- **2026-02-08**: fixed `indicators.fn_backfill_ohlcv(...)` 45m bucket calculation and rebuilt `indicators.ohlcv_45m`; see `/Users/vitolo/Desktop/projects/poly/README.md`
- **2026-02-09**: added/iterated on `indicators.oi_features` table + functions (see latest migrations `20260209170454`, `20260209171613`)
- **2026-02-09 (UTC)**: added RT-aligned training datasets (see migrations `20260209225708`, `20260209225903`) and recorded a completion note in `training.readme` (id 27)

Related repo artifacts:
- Plan: `/Users/vitolo/Desktop/projects/poly/docs/plans/2026-02-09-training-rt-alignment.md`
- Comparison harness: `/Users/vitolo/Desktop/projects/poly/scripts/compare_training_vs_indicators_15m.py`

### DB Lints (Supabase advisors)
- Multiple views are flagged as **SECURITY DEFINER** (notably `public.alpha_v4_predictions`, `public.v_predictions_with_metrics`, `public.trade_flow_live`, and `indicators.v_model_*`).
- Row Level Security (RLS) is flagged as disabled on many PostgREST-exposed tables (consistent with current “trusted backend” posture).
- Performance lints flag missing FK-covering indexes and duplicate/unused indexes in several places.

### Notable Extensions Installed
`pg_cron`, `pg_net`, `http`, `vector`, `pg_stat_statements`, `pg_partman`, `pg_graphql`, plus common tooling extensions (`pgcrypto`, `uuid-ossp`, etc.).

---

## 9. Comparing Training vs Realtime Data (Test → Production)

### First Principles (avoid false mismatches)
- **Realtime OHLCV is Coinbase-derived** (`public.raw_trades` → `indicators.ohlcv_*`).
- **Training OHLCV looks Binance-style** (`quote_volume`, `taker_buy_*`, `num_trades` strongly resemble Binance klines).
- Therefore, **do not expect** exact equality on OHLCV or indicator values unless you align data sources.
- If you train on `training.v_rt_dataset_from_indicators_15m_scoreable_current`, you are training on a snapshot of the **exact serving features** (`indicators.v_model_15m`) and **exact production labels** (`public.price_intervals_15m_live`), which removes the largest “feature math mismatch” class of issues without touching `indicators`.

### Recommended Comparison Scope
- Timeframe: **15m** (primary decision interval).
- Window: use the **overlap window** where both datasets exist:
  - Realtime 15m: from `2026-01-22 07:00Z` onward
  - Training 15m: through `2026-02-01 16:15Z`
  - Practical overlap: `2026-01-22 07:00Z` → `2026-02-01 16:00Z`
- Start with a “test” mode:
  - Use the `TEST-USD` pair (where present) to validate pipelines without polluting BTC/ETH/SOL dashboards.

### Shared Feature Columns (training.unified_15m ∩ indicators.v_model_15m)
There are **33** identically-named columns you can compare directly (after casting numeric types):
`open`, `high`, `low`, `close`, `volume`, `ema_9`, `ema_21`, `ema_50`, `sma_20`, `sma_50`, `rsi_7`, `rsi_14`, `rsi_21`, `macd_line`, `macd_signal`, `cci_20`, `mfi_14`, `momentum_10`, `roc_12`, `adx_14`, `atr_14`, `atr_21`, `cmf_20`, `cvd_50`, `cvd_100`, `vwap_50`, `vwap_96`, `keltner_upper`, `keltner_middle`, `keltner_lower`, `pivot`, `pivot_r1`, `pivot_s1`.

### Practical Comparison Strategy
1. **Coverage parity**: verify both sides have rows for the same timestamps (15m boundaries).
2. **Distribution sanity**: compare feature distributions (mean/std/percentiles) rather than expecting exact equality, unless data source is identical.
3. **Label alignment**: training uses `label`/`pct_change`; realtime uses `public.price_intervals_15m_live.outcome` and percent change computed from Coinbase candles. Ensure label definitions match before scoring.
4. **Promote test → prod**: once comparisons are stable for a test scope, run the same checks for BTC/ETH/SOL.

### Recommended Datasets (No Indicators Changes)

If your goal is “train in `training` and score on `indicators` with minimal skew”, prefer:
- Training set (best match): `training.v_rt_dataset_from_indicators_15m_scoreable_current`
  - Features are snapshotted directly from `indicators.v_model_15m` (same semantics as production serving).
  - Labels are snapshotted from `public.price_intervals_15m_live` (same semantics as production grading).
  - Note: the snapshot is **point-in-time**. Refresh via `training.refresh_rt_features_from_indicators_15m_v1()` when needed.
- Training set (historical / pretraining): `training.v_rt_dataset_15m_from_unified_scoreable_current`
  - Much larger history but not guaranteed to match realtime feature math or source.

Comparison harness:
- Script: `/Users/vitolo/Desktop/projects/poly/scripts/compare_training_vs_indicators_15m.py`
- Output: `/Users/vitolo/Desktop/projects/poly/scripts/output/compare_training_vs_indicators_15m_*.json`

### Example Join Skeleton (BTC 15m, overlap window)
```sql
with rt as (
  select
    split_part(pair, '-', 1) as symbol,
    bucket_time as ts,
    close::float8 as close_rt,
    ema_9::float8 as ema_9_rt,
    rsi_14::float8 as rsi_14_rt
  from indicators.v_model_15m
  where pair = 'BTC-USD'
    and bucket_time >= '2026-01-22 07:00:00+00'
    and bucket_time <  '2026-02-01 16:00:00+00'
),
tr as (
  select
    symbol,
    open_time as ts,
    close as close_tr,
    ema_9 as ema_9_tr,
    rsi_14 as rsi_14_tr
  from training.unified_15m
  where symbol = 'BTC'
    and open_time >= '2026-01-22 07:00:00+00'
    and open_time <  '2026-02-01 16:00:00+00'
)
select
  count(*) as joined_rows,
  avg(abs(rt.close_rt - tr.close_tr)) as avg_abs_close_diff,
  max(abs(rt.close_rt - tr.close_tr)) as max_abs_close_diff
from rt
join tr using (symbol, ts);
```

### Environment Separation (test vs production)
Right now there is **one** Supabase project and no branch/staging database via Supabase Branches. If you need strict separation:
- Option A: separate Supabase project (cleanest isolation)
- Option B: separate schemas (e.g. `rt_test`, `rt_prod`) with a shared set of views
- Option C: add an `env` column + strict RLS policies (works, but easy to misconfigure)

---

*This document is a living reference for schema and operational reality. Keep the dates current and prefer measured facts (counts, max timestamps, migrations) over assumptions.*
