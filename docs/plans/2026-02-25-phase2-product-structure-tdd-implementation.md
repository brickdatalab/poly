# Phase 2 Product Structure TDD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move from Phase 1 stabilization to a product-ready repository structure (`apps/runtime-synthetic`, `apps/api`, `ops`, `research`, `archive`) with strict freshness/fail-closed contracts and zero websocket-ingestion changes.

**Architecture:** Keep Supabase as source of truth (`supabase/` unchanged at repo root), expose a thin Python API layer for chart/query consumers, and preserve runtime compatibility wrappers until full cutover. All behavior-changing work is TDD-first with explicit red/green checkpoints and rollback-safe commits.

**Tech Stack:** Python 3.11+, pytest, existing runtime scripts, Supabase SQL/Edge Functions/cron, GitHub Actions.

---

## Constraints
1. Do not modify websocket ingestion behavior from GCP VM.
2. Do not remove compatibility wrappers until API/runtime consumers are fully cut over.
3. Any stale dependency must surface as fail-closed (`not_ready` / freshness error), never silently `ready`.
4. Every implementation task follows TDD (fail first -> minimal code -> pass).

## Task 1: Scaffold Product-Oriented App Layout

**Files:**
- Create: `apps/runtime-synthetic/README.md`
- Create: `apps/api/README.md`
- Modify: `README.md`
- Test: `tests/ops/test_repo_layout_contract.py`

**Step 1: Write failing layout contract test**
- Assert required top-level directories exist and are documented.

**Step 2: Run test to verify failure**
- Run: `pytest -q tests/ops/test_repo_layout_contract.py`
- Expected: FAIL because app docs/layout files do not exist yet.

**Step 3: Add minimal layout scaffolding**
- Create app directories and READMEs defining ownership and boundaries.
- Update root `README.md` with new layout map.

**Step 4: Run test to verify pass**
- Run: `pytest -q tests/ops/test_repo_layout_contract.py`
- Expected: PASS.

**Step 5: Commit**
- `git add apps/runtime-synthetic/README.md apps/api/README.md README.md tests/ops/test_repo_layout_contract.py`
- `git commit -m "chore: add phase2 app layout scaffolding and contract test"`

## Task 2: Promote Runtime Synthetic to Canonical App Module

**Files:**
- Create: `apps/runtime-synthetic/src/runtime_synthetic/__init__.py`
- Create: `apps/runtime-synthetic/src/runtime_synthetic/engine.py` (forwarder first, then canonical)
- Modify: `runtime/synthetic/engine.py`
- Modify: `syn-final/scripts/engine.py`
- Test: `tests/runtime/test_runtime_app_module_parity.py`

**Step 1: Write failing parity/import test**
- Assert imports through `apps/runtime-synthetic` and legacy wrappers resolve the same callable entrypoints.

**Step 2: Run test to verify failure**
- Run: `pytest -q tests/runtime/test_runtime_app_module_parity.py`
- Expected: FAIL (module path missing).

**Step 3: Implement minimal app module bridge**
- Add package under `apps/runtime-synthetic/src`.
- Forward current runtime engine through package without behavior change.
- Keep compatibility wrappers intact.

**Step 4: Run runtime parity suite**
- Run: `pytest -q tests/runtime/test_monkey_poly_parity.py tests/runtime/test_runtime_app_module_parity.py`
- Expected: PASS.

**Step 5: Commit**
- `git add apps/runtime-synthetic runtime/synthetic/engine.py syn-final/scripts/engine.py tests/runtime/test_runtime_app_module_parity.py`
- `git commit -m "refactor: expose runtime synthetic via app module with parity tests"`

## Task 3: Introduce API Skeleton with Freshness Metadata Contract

**Files:**
- Create: `apps/api/src/api_service/main.py`
- Create: `apps/api/src/api_service/contracts.py`
- Create: `apps/api/tests/test_api_contracts.py`
- Create: `apps/api/tests/test_freshness_metadata_contract.py`

**Step 1: Write failing API contract tests**
- Define expected response schema for:
  - candles endpoint
  - technical indicator endpoint
  - synthetic signal endpoint
- Require fields: `is_fresh`, `max_age_s`, `source_timestamp_utc`.

**Step 2: Run tests to verify failure**
- Run: `pytest -q apps/api/tests/test_api_contracts.py apps/api/tests/test_freshness_metadata_contract.py`
- Expected: FAIL (API files missing).

**Step 3: Implement minimal API skeleton**
- Add stub endpoints and typed contract models returning fixture-safe shapes.
- No production query logic yet; contract-first only.

**Step 4: Run tests to verify pass**
- Run: `pytest -q apps/api/tests/test_api_contracts.py apps/api/tests/test_freshness_metadata_contract.py`
- Expected: PASS.

**Step 5: Commit**
- `git add apps/api/src apps/api/tests`
- `git commit -m "feat: add api skeleton with freshness metadata contract"`

## Task 4: Implement Query Layer for OHLCV / Technical / Synthetic Reads

**Files:**
- Create: `apps/api/src/api_service/data_access.py`
- Create: `apps/api/tests/test_data_access_sql_shape.py`
- Modify: `apps/api/src/api_service/main.py`
- Test: `apps/api/tests/test_data_access_sql_shape.py`

**Step 1: Write failing SQL-shape tests**
- Assert timeframe filtering, pair filtering, bounds checks, and freshness age computation SQL fragments.

**Step 2: Run tests to verify failure**
- Run: `pytest -q apps/api/tests/test_data_access_sql_shape.py`
- Expected: FAIL.

**Step 3: Implement minimal query layer**
- Build read-only SQL helper functions with explicit parameter validation.
- Add freshness calculation from source timestamps.

**Step 4: Run tests to verify pass**
- Run: `pytest -q apps/api/tests/test_data_access_sql_shape.py apps/api/tests/test_api_contracts.py`
- Expected: PASS.

**Step 5: Commit**
- `git add apps/api/src/api_service/data_access.py apps/api/src/api_service/main.py apps/api/tests/test_data_access_sql_shape.py`
- `git commit -m "feat: add api query layer for candles/technicals/synthetics"`

## Task 5: Enforce Fail-Closed Freshness Gate in API + Runtime

**Files:**
- Create: `tests/runtime/test_fail_closed_stale_dependencies.py`
- Modify: `apps/api/src/api_service/main.py`
- Modify: `runtime/launchpad/server.py`
- Test: `tests/runtime/test_fail_closed_stale_dependencies.py`

**Step 1: Write failing fail-closed tests**
- Assert stale dependencies cannot produce successful "ready/fresh" payloads.
- Assert API returns explicit stale status/error metadata instead of silent success.

**Step 2: Run tests to verify failure**
- Run: `pytest -q tests/runtime/test_fail_closed_stale_dependencies.py`
- Expected: FAIL.

**Step 3: Implement minimal fail-closed checks**
- Add freshness guard helper shared by API/runtime call paths.
- Ensure stale dependencies are surfaced deterministically.

**Step 4: Run tests to verify pass**
- Run: `pytest -q tests/runtime/test_fail_closed_stale_dependencies.py tests/runtime/test_monkey_poly_parity.py`
- Expected: PASS.

**Step 5: Commit**
- `git add apps/api/src/api_service/main.py runtime/launchpad/server.py tests/runtime/test_fail_closed_stale_dependencies.py`
- `git commit -m "feat: enforce fail-closed freshness gates across runtime and api"`

## Task 6: Move Ops/Research Scripts to Canonical Lanes with Wrappers

**Files:**
- Create: `ops/scripts/...` (moved canonical targets)
- Create: `research/scripts/...` (moved canonical targets)
- Modify: legacy script entrypoints with thin forwarders
- Modify: `docs/architecture/repo-script-inventory.csv`
- Test: `tests/ops/test_script_forwarder_contract.py`

**Step 1: Write failing forwarder contract tests**
- Assert legacy paths still execute and point to canonical lanes.

**Step 2: Run tests to verify failure**
- Run: `pytest -q tests/ops/test_script_forwarder_contract.py`
- Expected: FAIL.

**Step 3: Implement minimal moves + wrappers**
- Move highest-value ops/research scripts first.
- Add wrappers in old paths.
- Update inventory metadata.

**Step 4: Run tests to verify pass**
- Run: `pytest -q tests/ops/test_script_forwarder_contract.py tests/ops/test_repo_layout_contract.py`
- Expected: PASS.

**Step 5: Commit**
- `git add ops research scripts docs/architecture/repo-script-inventory.csv tests/ops/test_script_forwarder_contract.py`
- `git commit -m "refactor: canonicalize ops/research script lanes with compatibility wrappers"`

## Task 7: CI Gates for Phase 2 Contracts

**Files:**
- Modify: `.github/workflows/ops-db-guards.yml`
- Create: `.github/workflows/phase2-contracts.yml`
- Test: `tests/ops/test_ci_workflow_contracts.py`

**Step 1: Write failing workflow contract test**
- Assert workflows run runtime parity + API contract tests + fail-closed tests.

**Step 2: Run test to verify failure**
- Run: `pytest -q tests/ops/test_ci_workflow_contracts.py`
- Expected: FAIL.

**Step 3: Implement minimal CI workflow updates**
- Add workflow commands and branch/path filters.
- Keep jobs bounded and deterministic.

**Step 4: Run tests to verify pass**
- Run: `pytest -q tests/ops/test_ci_workflow_contracts.py tests/ops`
- Expected: PASS.

**Step 5: Commit**
- `git add .github/workflows tests/ops/test_ci_workflow_contracts.py`
- `git commit -m "ci: add phase2 contract gates for runtime and api"`

## Task 8: Cutover and Prune (Only After Stable Window)

**Files:**
- Modify: `docs/runbooks/gitops-operating-model.md`
- Modify: `docs/runbooks/runtime-synthetic.md`
- Modify/Delete: compatibility wrappers after proven unused
- Test: `tests/runtime/test_no_legacy_runtime_imports.py`

**Step 1: Write failing no-legacy-import test**
- Assert production entrypoints no longer rely on deprecated paths.

**Step 2: Run test to verify failure**
- Run: `pytest -q tests/runtime/test_no_legacy_runtime_imports.py`
- Expected: FAIL.

**Step 3: Implement minimal cutover**
- Switch consumers to canonical app lanes.
- Remove wrappers only where zero references remain.

**Step 4: Run full verification suite**
- Run: `pytest -q tests/runtime tests/ops apps/api/tests`
- Expected: PASS.

**Step 5: Commit**
- `git add docs/runbooks runtime syn-final apps tests`
- `git commit -m "refactor: complete phase2 cutover and prune legacy runtime paths"`

---

## Phase 2 Acceptance Gate
1. Runtime parity remains green.
2. API contracts return freshness metadata on all endpoints.
3. Stale dependencies fail closed, never silent-ready.
4. Ops/research classification and lane ownership are deterministic.
5. Compatibility wrappers removed only after zero-reference proof.

## Rollback Plan
1. Keep wrappers until final task; rollback by reverting cutover commits.
2. Preserve `supabase/` schema migrations as forward-only; application rollback happens at code-entrypoint level.
3. If API contract regressions occur, disable API workflow path while keeping runtime unaffected.
