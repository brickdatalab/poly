# Training Schema Review

This folder contains a scriptable, repeatable review suite that queries Supabase Postgres via `psql` (no MCP data pumping) and writes timestamped artifacts to:

`/Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/runs/<UTC_TIMESTAMP>/`

## Run

```bash
python3 /Users/vitolo/Desktop/projects/poly/scripts/training_schema_review/run_all.py --jobs 8
```

## Notes

- Reads `/Users/vitolo/Desktop/projects/poly/.env` for `SUPABASE_DB_URL` (preferred) or derives DB host from `SUPABASE_URL`.
- Uses `SUPABASE_DB_PASSWORD` via `PGPASSWORD`. Secrets are never printed.
- Defaults are tuned for a beefy local machine + an 8-core Supabase Postgres.

