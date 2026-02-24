# Codex Signals Realtime Playground

Localhost dashboard for BTC/ETH 15m codex signal monitoring.

## Run

```bash
python scripts/codex_signals_playground/run_realtime_dashboard.py
```

This will:
- Start a local server (default `http://127.0.0.1:8787`)
- Open your default browser automatically
- Evaluate windows at `:02, :17, :32, :47` UTC-aligned decision times
- Trigger synthetic + codex enqueue/process cycles, then append BTC/ETH rows to in-memory session table

## Options

```bash
python scripts/codex_signals_playground/run_realtime_dashboard.py \
  --host 127.0.0.1 \
  --port 8787 \
  --sigma-min 0.25 \
  --pairs BTC-USD,ETH-USD \
  --no-open
```

## Notes
- Session is ephemeral by design (resets when script stops).
- Requires either `SUPABASE_DB_URL`, or `SUPABASE_URL` + `SUPABASE_DB_PASSWORD` in `.env`.
- Uses the existing pipeline functions:
  - `indicators.fn_enqueue_synthetic_jobs`
  - `indicators.fn_process_synthetic_jobs`
  - `indicators.fn_enqueue_codex_signal_jobs`
  - `indicators.fn_process_codex_signal_jobs`
