# GitOps Operating Model

## Scope

This runbook defines how production Supabase and pipeline changes are made and audited.

## Hard Rules

1. `main` is protected. No direct pushes.
2. Any DB change must ship as SQL migration in `supabase/migrations`.
3. Any Edge Function change must exist under `supabase/functions`.
4. Dashboard break-glass changes must be backported via PR within 24 hours.
5. GCP raw websocket ingestion behavior is treated as critical infrastructure and is not changed without explicit approval.

## PR Requirements

1. PR includes risk classification and rollback notes.
2. CI passes.
3. Supabase Preview check passes for `supabase/**` changes.
4. At least one reviewer approves.

## Deployment Policy

1. Preview-first for any migration or function change.
2. Production deploy on merge only after required checks pass.
3. Post-merge smoke checks:
   - `indicator-worker` invoke succeeds.
   - `indicators.job_queue` pending trend is healthy.
   - Freshness checks for `ohlcv_1m`, `indicator_values`, `oi_features`.

## Incident Policy

1. Declare incident and record UTC timeline.
2. Apply minimal safe fix.
3. Validate recovery with runbook queries.
4. Backport and merge permanent prevention change.

