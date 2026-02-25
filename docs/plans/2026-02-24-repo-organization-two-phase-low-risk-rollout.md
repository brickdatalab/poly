# Repo Organization Two-Phase Low-Risk Rollout Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cleanly organize the `poly` repo so runtime synthetic indicators, Supabase assets, and operational utilities are clearly separated, production-safe, and maintainable for eventual Vercel chart/API integration.

**Architecture:** Keep `supabase/` at repo root for GitHub/Supabase integration. Establish one canonical runtime lane for synthetic indicators and one operational lane for maintenance/recovery scripts. Move in two phases: first stabilize without breaking current behavior, then restructure into product-ready app modules with compatibility shims.

**Tech Stack:** Python runtime scripts, Supabase SQL migrations/functions, pg_cron, pytest, GitHub Actions.

---

## Why This Plan
Current repo state mixes:
1. Production/runtime scripts
2. Recovery/utility scripts
3. Research/backtest scripts
4. Historical/dead artifacts

This creates drift risk and makes ownership unclear. We need deterministic boundaries.

---

## Hard Constraints
1. Do not change websocket ingestion behavior from GCP VM.
2. Keep all Supabase deployment assets in `supabase/`.
3. No risky “big-bang” moves.
4. Runtime synthetic outputs must stay accurate and parity-tested during migration.

---

## Canonical Classification Model

Every executable/script must be tagged as one of:
1. `runtime` -> live production path
2. `ops` -> recovery, backfill, diagnostics, health
3. `research` -> experiments/backtests/notebooks
4. `archive` -> old/deprecated (read-only)

Decision rule:
1. Is it required to compute or serve live signals now? -> `runtime`
2. Is it required only for break/fix or maintenance? -> `ops`
3. Is it for analysis or model exploration? -> `research`
4. Otherwise -> `archive` (or delete if disposable artifact)

---

## Known-Good Sources To Preserve
User-confirmed good scripts:
1. `/Users/vitolo/Desktop/projects/monkey/syn-final/scripts/*`
2. `/Users/vitolo/Desktop/projects/monkey/t2_window_down_signal.py`
3. `/Users/vitolo/Desktop/projects/monkey/t2_window_up_signal.py`
4. `/Users/vitolo/Desktop/projects/monkey/server.py` (launchpad/dev server lane)

---

## Phase 1 (Low-Risk Stabilization, No Big Moves)

### Outcome
Runtime is standardized and documented, with compatibility maintained and clutter contained.

### Task 1: Inventory + Ownership Matrix
**Create**
- `docs/architecture/repo-script-inventory.csv`
- `docs/architecture/repo-script-classification.md`

**Actions**
1. Enumerate scripts under:
   - `scripts/`
   - `syn-final/`
   - repo root python scripts
2. For each script capture:
   - class (`runtime|ops|research|archive`)
   - owner
   - source-of-truth path
   - run command
   - dependencies (tables/functions)

### Task 2: Canonical Runtime Lane (without breaking existing calls)
**Create**
- `runtime/synthetic/`
- `runtime/launchpad/`

**Actions**
1. Bring in known-good monkey runtime files into canonical runtime lane:
   - `runtime/synthetic/engine.py`
   - `runtime/synthetic/run_all_signal_producers.py`
   - `runtime/synthetic/t0_*.py`, `t1_*.py`, `t2_*.py`
   - `runtime/synthetic/window/t2_window_up_signal.py`
   - `runtime/synthetic/window/t2_window_down_signal.py`
   - `runtime/launchpad/server.py`
2. Keep existing paths functional via thin compatibility wrappers (import/forward).
3. Do not delete old paths in Phase 1.

### Task 3: Runtime Parity Gate
**Create**
- `tests/runtime/test_monkey_poly_parity.py`
- `tests/runtime/test_window_signal_parity.py`

**Actions**
1. Compare old vs new runtime outputs for same `bucket_time` and pair set.
2. Fail migration if outputs diverge beyond expected tolerance.

### Task 4: Ops/Research Separation
**Create**
- `ops/` and `research/` top-level directories
- `docs/operations/ops-catalog.md`
- `docs/research/research-catalog.md`

**Actions**
1. Copy (not delete) scripts into classified folders first.
2. Add wrappers from old locations to new canonical paths for compatibility.
3. Exclude generated artifacts and caches from git.

### Task 5: Hygiene + Repo Policy
**Modify**
- `.gitignore`
- `README.md`

**Actions**
1. Enforce no `.DS_Store`, `__pycache__`, local outputs, ad-hoc dumps in git.
2. Add “allowed locations by class” policy.
3. Add script template header requiring `CLASS`, `OWNER`, `RUNBOOK`.

### Phase 1 Acceptance Criteria
1. Known-good monkey runtime scripts are present in canonical runtime lane.
2. Existing operational entrypoints still work (compatibility wrappers).
3. Parity tests pass.
4. All executable scripts are classified and documented.
5. No accidental runtime behavior changes.

---

## Phase 2 (Product-Ready Structure For Vercel/API)

### Outcome
Repo is cleanly app-oriented and ready for charting/query interfaces.

### Target Structure
1. `apps/runtime-synthetic/` -> production signal runtime
2. `apps/api/` -> chart/API service layer for OHLCV, technicals, synthetics
3. `supabase/` -> migrations/functions (unchanged root placement)
4. `ops/` -> backfill/recovery/health
5. `research/` -> non-production analysis
6. `archive/` -> legacy frozen assets

### Task 1: Extract Runtime Into App Module
1. Move canonical runtime files from `runtime/synthetic/` into `apps/runtime-synthetic/`.
2. Keep compatibility wrappers until consumers are cut over.

### Task 2: Introduce API Contract Layer
1. Add APIs for charting:
   - candles by timeframe/range
   - technical indicators by config/range
   - synthetic signals by config/range
2. Add freshness metadata in API responses (`is_fresh`, `max_age_s`).

### Task 3: Hard Data Contracts
1. Add schema contracts and tests for:
   - technical indicators
   - synthetic indicator dependency readiness
2. Ensure fail-closed behavior for stale dependencies.

### Task 4: Final Cutover and Prune
1. Remove wrappers only after no references remain.
2. Move obsolete scripts to `archive/` or delete.

### Phase 2 Acceptance Criteria
1. Clean app-oriented tree with explicit boundaries.
2. Vercel-facing API can serve chart overlays for OHLCV + technical + synthetic.
3. Runtime accuracy and freshness tests remain green.
4. Legacy clutter removed from active paths.

---

## Rollback Strategy
1. Phase 1: revert wrappers/canonical lane commits; no destructive move performed.
2. Phase 2: preserve wrappers until cutover complete; rollback by toggling entrypoints.

---

## Execution Sequence (Recommended)
1. Execute Phase 1 completely.
2. Stabilize for 24h with runtime monitoring.
3. Execute Phase 2 in small PRs (one module at a time).

---

## Notes For This Repo
1. `poly/syn-final/scripts` and `monkey/syn-final/scripts` currently diverge (`engine.py`, runner, script sets).
2. `monkey` includes t0/t1/t2 wrappers that are explicitly desired and should be preserved.
3. `poly` has additional check/backtest scripts that should likely be classified into `ops` or `research`, not mixed into runtime.
