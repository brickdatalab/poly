# Repo Script Classification

## Purpose
This document defines the script classification policy for this repository and the allowed execution lanes. It is the authority for deciding whether a script is production runtime, operational maintenance, research, or archived legacy.

## Classes
Use exactly one class per executable script.

1. `runtime`
- Live production execution path.
- Required for current signal computation or serving.
- Changes require parity verification and runbook updates.

2. `ops`
- Recovery, backfill, diagnostics, health checks, incident tooling.
- Safe to run in production only through runbooks and bounded windows.

3. `research`
- Experimentation, backtests, analytics, model exploration.
- Must not be part of live runtime paths.

4. `archive`
- Historical/deprecated scripts.
- Read-only reference; not part of active workflows.

## Decision Tree
1. Is this script required for current live signal generation or serving?
- Yes -> `runtime`
- No -> step 2
2. Is this script used for break/fix, backfills, health checks, or operations?
- Yes -> `ops`
- No -> step 3
3. Is this script exploratory, experimental, or for analysis only?
- Yes -> `research`
- No -> `archive`

## Allowed Locations By Class
1. `runtime`
- Canonical: `runtime/`
- Compatibility entrypoints allowed under legacy paths (`syn-final/scripts/...`) only as wrappers forwarding to `runtime/`.

2. `ops`
- Canonical operational scripts remain under `scripts/ops/` and related recovery folders during Phase 1.
- Future location target in Phase 2: `ops/`.

3. `research`
- Canonical research scripts remain under `scripts/...` research namespaces during Phase 1.
- Future location target in Phase 2: `research/`.

4. `archive`
- Archive-only code should live outside active runtime/ops lanes; this repo currently keeps archive history in git rather than a committed `scripts/scripts_past/` tree.

## Ownership
1. `core-runtime`
- Owns `runtime/*` and compatibility wrappers for runtime entrypoints.

2. `ops-reliability`
- Owns health, recovery, backfill, and SLO guardrails.

3. `quant-research`
- Owns exploratory and analysis scripts.

4. `archive-maintainer`
- Owns retention/pruning of deprecated scripts.

## Current Canonical Runtime Lane
1. `runtime/synthetic/*`
- Source of truth for synthetic runtime logic imported from known-good `monkey` scripts.

2. `runtime/synthetic/window/*`
- Source of truth for window up/down signal scripts.

3. `runtime/launchpad/server.py`
- Launchpad/dev server lane for running runtime synthetic indicators.

4. Compatibility wrappers:
- `syn-final/scripts/engine.py`
- `syn-final/scripts/run_all_signal_producers.py`

## Verification Requirements
Before merging runtime-affecting changes:

1. Run runtime parity tests:
- `pytest tests/runtime -q`

2. Run operational contract tests:
- `pytest tests/ops -q`

3. Validate wrapper forwarding remains intact:
- Legacy entrypoints resolve and execute canonical `runtime/` modules.

## Non-Negotiables
1. Do not modify websocket ingestion behavior on GCP VM from this repo reorganization track.
2. Do not execute archive scripts in production paths.
3. Do not introduce new runtime entrypoints outside canonical `runtime/` without explicit classification and runbook update.
