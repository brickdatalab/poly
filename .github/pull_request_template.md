## Summary

- What changed:
- Why:
- Risk level:

## Safety Checklist

- [ ] No secrets added or modified in repo
- [ ] Any production DB change is represented as a migration in `supabase/migrations/`
- [ ] I did **not** modify GCP raw websocket ingestion behavior unless explicitly approved
- [ ] Recovery/backfill steps are idempotent and documented
- [ ] Rollback plan is included in PR description

## Verification

- [ ] Local checks passed
- [ ] Supabase preview check passed
- [ ] Data freshness and queue health queries included in PR notes

## Production Impact

- [ ] No production impact
- [ ] Safe schema change (additive)
- [ ] Runtime behavior change (explain below)

### Notes

