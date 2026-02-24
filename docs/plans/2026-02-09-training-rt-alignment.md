# Training RT-Alignment Plan (No Changes to `indicators` Schema)

**Date (UTC)**: 2026-02-09  
**Scope**: Add *new* objects to the `training` schema so models trained on `training` generalize cleanly when scored on `indicators` (and on newly arriving `indicators` data).  
**Non-negotiable constraint**: **Do not change anything in `indicators`** (tables, functions, views, semantics, key points).

---

## Goals

1. Build an **RT-compatible training dataset** whose *row grain, timestamps, feature definitions, and labels* match what production scoring uses from `indicators` (for 15m, practically `indicators.v_model_15m`).
2. Make “train on `training`” and “test/score on `indicators`” comparable by minimizing:
   - feature-definition skew
   - timestamp/label misalignment
   - missingness/warmup mismatch
   - training-serving skew
3. Preserve existing `training.*` tables; implement via **versioned additive objects** (`*_v1`, `*_current` views).

---

## Guiding Decisions (Lock Early)

1. **Target timeframe**: `15m` only (until parity is proven).
2. **Feature set v1**: start with the **intersection** of `training.unified_15m` and `indicators.v_model_15m` that share identical names (currently 33 columns).
3. **Label rule**: must match the realtime grading logic (UP/DOWN/FLAT thresholds, flat handling, window boundaries).
4. **“Scoreable row” rule**: must match production reality:
   - only score *closed* 15m candles
   - drop rows where any required feature is NULL
   - enforce a fixed warmup burn-in per symbol (based on longest lookback)

---

## Phase 0: Snapshot and Contract (1-2 hours)

### Task 0.1: Freeze the serving contract

**Deliverable**: a small “contract” document + SQL query outputs.

- Capture:
  - `indicators.v_model_15m` column list, types, and any computed/nullable behavior
  - exact label/outcome semantics currently used in production (likely via `public.price_intervals_15m_live`)
  - definitive feature list v1 (33 shared columns)

**Acceptance criteria**
- We can point at a single list of `feature_columns_v1[]` and a single label definition.
- Everyone agrees what “a row at time T” means.

---

## Phase 1: Make `training` speak in RT primitives (15m candles) (0.5-1 day)

### Task 1.1: Create RT-like base candle view/table

**Add (no modifications to existing tables)**:
- `training.rt_ohlcv_15m_v1` (view or table)

**Columns (match realtime naming)**
- `pair` (e.g. `BTC-USD`)
- `bucket_time` (15m boundary; `timestamptz`)
- `open`, `high`, `low`, `close`, `volume`
- `buy_volume`, `sell_volume`, `trade_count`
- `source` (text; e.g. `binance_spot_15m`)

**Mapping from existing**
- from `training.spot_15m`:
  - `pair := symbol || '-USD'`
  - `bucket_time := open_time`
  - `buy_volume := taker_buy_base_vol`
  - `sell_volume := greatest(volume - taker_buy_base_vol, 0)`
  - `trade_count := num_trades::int`

**Add constraints**
- bucket_time on 15m boundary (`extract(minute) % 15 = 0 and extract(second)=0`)
- non-negative volumes

**Acceptance criteria**
- Counts per symbol match `training.spot_15m` exactly.
- Zero off-grid timestamps.

---

## Phase 2: RT-compatible feature table inside `training` (1-2 days)

### Task 2.1: Create versioned feature table computed from RT-like candles

**Add**
- `training.rt_features_15m_v1` (table; materialized for stable training reproducibility)
- `training.v_rt_features_15m_current` (view → points to v1)

**Feature set v1**
- Start with the 33 shared columns (OHLCV + selected indicators):
  - OHLCV: `open, high, low, close, volume`
  - `ema_9, ema_21, ema_50`
  - `sma_20, sma_50`
  - `rsi_7, rsi_14, rsi_21`
  - `macd_line, macd_signal`
  - `cci_20, mfi_14, momentum_10, roc_12`
  - `adx_14, atr_14, atr_21`
  - `cmf_20, cvd_50, cvd_100`
  - `vwap_50, vwap_96`
  - `keltner_upper, keltner_middle, keltner_lower`
  - `pivot, pivot_r1, pivot_s1`

**Critical requirement**
- Compute these features using **the same definitions** production scoring uses (i.e. mirror `indicators` semantics).
- Since `indicators` cannot be changed, the most robust approach is:
  - extract the *relevant* indicator logic from `indicators` (functions/SQL patterns)
  - implement *equivalent* functions inside `training` (namespaced; no dependency on `indicators`)

**Performance notes**
- Build per symbol with deterministic ordering on `bucket_time`.
- Store `computed_at`, `feature_version`.

**Acceptance criteria**
- `rt_features_15m_v1` has one row per `(pair, bucket_time)` present in `rt_ohlcv_15m_v1` (minus burn-in).
- No unexpected NULL spikes after burn-in.

---

## Phase 3: Labels that match realtime grading (0.5-1 day)

### Task 3.1: Create versioned label table

**Add**
- `training.rt_labels_15m_v1` (table)
- `training.v_rt_labels_15m_current` (view → points to v1)

**Label semantics**
- Based on next 15m close:
  - `next_close` at `bucket_time + interval '15 minutes'`
  - `pct_change := (next_close - close) / close`
  - `label := UP/DOWN/FLAT` using the same FLAT threshold used by production

**Include**
- `event_start := bucket_time`
- `event_end := bucket_time + 15m`
- `start_price := close` (or explicit “interval start” rule if production uses open)
- `end_price := next_close`
- `label_version`

**Acceptance criteria**
- Label distribution and flat-rate are stable and explainable.
- No leakage: labels only reference future candles.

---

## Phase 4: Assemble the training dataset view (0.5 day)

### Task 4.1: Create the canonical dataset view for model training

**Add**
- `training.v_rt_dataset_15m_v1` (view)
- `training.v_rt_dataset_15m_current` (view → points to v1)

**Join keys**
- `(pair, bucket_time)`

**Row gating**
- `is_scoreable` boolean, plus a filtered view `training.v_rt_dataset_15m_scoreable_current`:
  - requires all `feature_columns_v1` non-null
  - requires `bucket_time <= max(bucket_time) - 15m` (closed interval)
  - burn-in window per pair

**Acceptance criteria**
- A model training script can read from a single view with stable schema.

---

## Phase 5: Parity Harness (test before trusting) (1 day)

### Task 5.1: Add a comparison script (distribution, not equality)

**Add (repo)**
- `/Users/vitolo/Desktop/projects/poly/scripts/compare_training_vs_indicators_15m.py`
- Output JSON reports under `/Users/vitolo/Desktop/projects/poly/scripts/output/`

**Comparisons**
1. Coverage parity on overlap window:
   - overlap: `2026-01-22 07:00Z` → `2026-02-01 16:00Z` (where both exist)
2. For each feature in v1:
   - mean/std
   - p50/p90/p99
   - missing-rate
   - correlation with label

**Important note**
- Exact equality is not expected if the candle source differs (Coinbase realtime vs Binance training). We care about:
  - stable distributions
  - no pathological drifts
  - label alignment

**Acceptance criteria**
- No features are wildly out-of-family (e.g., RSI outside [0,100], ATR negative, CMF outside [-1,1]).
- Missingness is consistent with production scoring expectations.

---

## Phase 6: Add a “domain-bridge” dataset (most impactful for real-world scoring) (0.5-1 day)

This is the highest leverage step if you want strong realtime performance without changing `indicators`.

### Task 6.1: Snapshot `indicators.v_model_15m` into `training` for recent periods

**Add**
- `training.rt_features_from_indicators_15m_v1` (table)
- `training.rt_labels_from_public_15m_v1` (table; derived from `public.price_intervals_15m_live`)
- `training.v_rt_dataset_from_indicators_15m_current` (view)

**Why**
- This produces a training dataset with *identical* feature semantics to production serving because it literally uses the serving view output.
- Use it for:
  - calibration
  - fine-tuning
  - post-deploy monitoring baselines

**Acceptance criteria**
- The dataset updates (batch/cron/manual) without impacting `indicators`.

---

## Execution Mechanics

### Applying DB changes
- Use Supabase migrations (`supabase_migrations`) via:
  - MCP: `mcp__supabase__apply_migration` (preferred for auditable changes)
  - Keep a local copy of applied SQL under `/Users/vitolo/Desktop/projects/poly/scripts/output/` for traceability.

### Rollback
- All objects are additive/versioned.
- Rollback is: drop `training.rt_*_v1` objects and revert `*_current` views.

---

## Definition of Done

1. `training.v_rt_dataset_15m_scoreable_current` exists and is stable.
2. Training labels match production semantics (UP/DOWN/FLAT logic).
3. Comparison harness runs and produces reports showing no pathological skew.
4. Optional but recommended: `training.v_rt_dataset_from_indicators_15m_current` exists for calibration and real-world evaluation.

