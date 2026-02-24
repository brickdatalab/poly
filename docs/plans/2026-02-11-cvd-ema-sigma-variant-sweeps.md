# CVD + EMA Spread Sigma Sweeps Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run 4 variants per indicator (CVD ROC, EMA spread ROC), plus 2 rolling `min_n` settings (500 and 1000), and report whether these pre-event changes correlate with the 15m event outcome across all quarter-hour starts.

**Architecture:** A SQL-first evaluator that computes one feature per 15m event (`t0` at `:00/:15/:30/:45`), applies sigma-trigger logic (UP/DOWN tails), and summarizes accuracy/coverage on train vs last-48h. A Python runner fans out independent variant queries in parallel.

**Tech Stack:** Python 3, `psql` via `SUPABASE_DB_URL`, Postgres window functions.

---

## Definitions (Shared)

**Symbol:** `BTC` (for this phase)

**Event / label (TRAINING SCHEMA ONLY for correlation discovery):**
- Event start `t0`: rows from `training.spot_15m` where `minute in (0,15,30,45)`.
- Outcome: `outcome_up = 1 if close > open else 0` (exclude flats).

**Feature timestamp to avoid leakage:**
- We do NOT use indicator values aligned to the *same* event candle.
- For an event at `t0`, we compute features at `t_feat = t0 - 15 minutes` (the most recently completed 15m candle before the event start).

**Decision time constraint (not used in training-phase computation):**
- Production can bet by `t0+2m` / `t0+3m`, but training-phase correlation discovery is done at the 15m candle boundary using 15m indicators available as of `t0`.
- Once a training correlation is found, we will re-check it on `indicators` (production-aligned) and enforce the `t0+2m` decision rule there.

**Sigma ladder:** `k ∈ {0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0}`

**Trigger rule (per k):**
- UP prediction if `x > mu + k*sd`
- DOWN prediction if `x < mu - k*sd`

**Gating rule:**
- Phase 1: Training schema (global history) only.
- Only if Phase 1 shows a strong correlation (target: >=70% accuracy for at least one sigma level with non-trivial coverage) do we proceed to Phase 2 (apply the same logic on `indicators` for a last-48h check).

---

## Indicator 1: CVD (cvd_50)

**Source series:** `training.spot_15m_indicators.cvd_50` for `BTC`.

**Feature:** rate-of-change in CVD into the event (computed on 15m grid, using `t_feat`):
- `x = cvd_50(t_feat) - cvd_50(t_feat - lookback)`

Because this is a 15m indicator table, `lookback` is expressed in 15m increments.

**Variants (4):**
1. lookback=15m (1 candle), normalization=global (mu/sd fit on full training history)
2. lookback=60m (4 candles), normalization=global
3. lookback=15m, normalization=rolling 21d (mu/sd computed from prior 21d of events)
4. lookback=60m, normalization=rolling 21d

**Rolling stability settings:** For variants 3 and 4, run twice:
- `min_n=500`
- `min_n=1000`

---

## Indicator 2: EMA Spread / Crossover Pressure

**Source series:** `training.spot_15m_indicators.ema_9`, `ema_21`.

**Derived spread at time t:**
- `spread_pct(t) = ((ema_9(t) - ema_21(t)) / nullif(ema_21(t), 0)) * 100`

**Feature:** spread ROC into the event (computed on 15m grid, using `t_feat`):
- `x = spread_pct(t_feat) - spread_pct(t_feat - lookback)`

**Variants (4):**
1. lookback=15m (1 candle), normalization=global
2. lookback=60m (4 candles), normalization=global
3. lookback=15m, normalization=rolling 21d
4. lookback=60m, normalization=rolling 21d

**Rolling stability settings:** For variants 3 and 4, run twice:
- `min_n=500`
- `min_n=1000`

---

## Output Requirements

For each variant, produce:
- `results.csv` with rows: `{side(UP|DOWN), sigma, n_pred, coverage_pct, accuracy_pct}` on **training schema only**.
- `REPORT.md` (concise) highlighting:
  - best sigma operating points with accuracy >= 70% on training
  - trigger counts (so we can tell if it’s actionable)

If (and only if) the training report has promising operating points, create a second report that re-runs the same variant on `indicators` for the last 48 hours.

Create one top-level run folder:
- `scripts/output/indicator_sigma_sweeps/<UTC>/`
  - `cvd_roc_5m_global/results.csv`
  - `cvd_roc_5m_rolling_min500/results.csv`
  - ... etc

---

## Parallelism Plan

- Run each variant as a separate DB query.
- Dispatch queries with `ProcessPoolExecutor`.
- Default `--jobs 8` (safe for DB + local) but allow `--jobs 16`.
- DB-side computation will dominate; concurrency is bounded to avoid overwhelming the DB.

---

## Tasks

### Task 1: Create the variant runner

**Files:**
- Create: `scripts/indicator_sigma_sweeps/run_two_indicator_sweeps.py`

**Step 1: Implement variant list + CLI**
- CLI args: `--jobs`, `--lookback-days 21`, `--test-hours 48`, `--min-sigma-list`, `--rolling-min-n 500,1000`

**Step 2: Implement DB query generator**
- One generator that accepts:
  - `indicator_name` (`cvd`, `ema_spread`)
  - `lookback_minutes` (5 or 15)
  - `normalization` (`global` or `rolling`)
  - rolling params (`lookback_days`, `min_n`)
  - test split (`test_hours`)

**Step 3: Implement result writer**
- Use `psql \copy (...) TO STDOUT WITH CSV HEADER` to write results.
- Write a short `REPORT.md` per variant.

### Task 2: Run the sweeps

**Step 1: Run the runner with rolling min_n=500 and min_n=1000**
Run:
- `python3 scripts/indicator_sigma_sweeps/run_two_indicator_sweeps.py --jobs 8`

**Step 2: Inspect results for 70%+ points**
- Confirm any sigma threshold that yields >=70% accuracy and non-trivial coverage.

### Task 3: Summarize findings

**Files:**
- Create: `docs/discoveries/2026-02-11-cvd-ema-sigma-sweeps.md`

**Step 1: Write concise conclusions**
- “Correlation exists / flat”
- “Best operating points”
- “Holds in last 48h or not”

---

## Execution Handoff

Plan saved to `docs/plans/2026-02-11-cvd-ema-sigma-variant-sweeps.md`.

Two execution options:
1. Subagent-Driven (this session)
2. Parallel Session (separate)

Which approach?
