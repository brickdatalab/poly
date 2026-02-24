# Synthetic Indicators Schema

This document describes the synthetic indicator subsystem added under `indicators`.

## Design Goals
- Non-breaking: no modifications to existing indicator compute tables/functions.
- Metadata-driven: synthetic indicators are config-based.
- Idempotent and backfillable: safe upserts over any historical window.
- Signal-friendly serving: one pivoted view for runtime filter mapping.

## Tables

### indicators.synthetic_indicator_configs
Configuration catalog for synthetic indicators.

Columns:
- `config_id` (`text`, PK): stable synthetic config key.
- `indicator_name` (`text`): readable synthetic name.
- `category` (`text`): synthetic grouping.
- `timeframe` (`text`): output timeframe (15m event grid).
- `decision_phase` (`text`): `t_plus_1m` or `t_plus_2m`.
- `params` (`jsonb`): formula constants/lookbacks/ladder metadata.
- `output_columns` (`jsonb`): semantic mapping of `v1..v5`.
- `description` (`text`): purpose and interpretation.
- `is_active` (`boolean`): compute participation switch.
- `created_at` (`timestamptz`): creation timestamp.

### indicators.synthetic_indicator_values
Long-form synthetic values.

Columns:
- `id` (`bigint`): surrogate id.
- `pair` (`text`): market pair.
- `bucket_time` (`timestamptz`): 15m event boundary (`t0`).
- `config_id` (`text`): FK to synthetic config.
- `v1..v5` (`numeric`): synthetic score and components.
- `source_time` (`timestamptz`): latest source input timestamp.
- `computed_at` (`timestamptz`): compute timestamp.
- `quality_flags` (`jsonb`): missing-data/quality diagnostics.

Uniqueness:
- `(pair, bucket_time, config_id)` for idempotent upsert.

### indicators.synthetic_job_queue
Dedicated synthetic processing queue.

Columns:
- `id` (`bigint`): queue id.
- `pair` (`text`)
- `bucket_time` (`timestamptz`)
- `decision_phase` (`text`)
- `status` (`text`): `pending|running|done|failed`
- `attempts` (`integer`)
- `error_message` (`text`)
- `created_at`, `started_at`, `completed_at` (`timestamptz`)

Uniqueness:
- `(pair, bucket_time, decision_phase)`.

## Functions

### Compute Helpers
- `indicators.fn_syn_iv_value(pair, bucket_time, config_id, col, exact)`
- `indicators.fn_syn_upsert_value(...)`

### Per-Indicator Compute
- `indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio(pair, bucket_time)`
- `indicators.fn_compute_synthetic_rsi_velocity_5m(pair, bucket_time)`
- `indicators.fn_compute_synthetic_early_impulse_liq_align_2m(pair, bucket_time)`
- `indicators.fn_compute_synthetic_oi_funding_impulse_2m(pair, bucket_time)`
- `indicators.fn_compute_synthetic_early_momentum_divergence(pair, bucket_time)`
- `indicators.fn_compute_synthetic_order_flow_accel_regime(pair, bucket_time)`

### Dispatcher
- `indicators.fn_compute_synthetic_for_bucket(pair, bucket_time, config_id)`
- `indicators.fn_compute_all_synthetic_for_bucket(pair, bucket_time)`

### Backfill and Queue
- `indicators.fn_backfill_synthetic_indicators(from_ts, to_ts, pairs[])`
- `indicators.fn_enqueue_synthetic_jobs(lookback interval)`
- `indicators.fn_process_synthetic_jobs(batch_size)`

## Serving View

### indicators.v_synthetic_signal_inputs
Pivoted view for signal scripts and filter logic. One row per `(pair, bucket_time)` containing:
- six primary synthetic scores
- selected component diagnostics
- feature-phase readiness flags (`has_t_plus_1m_features`, `has_t_plus_2m_features`)
- latest `synthetic_computed_at`

## Six Synthetic Indicators

1. `syn_mtf_signed_efficiency_ratio_5m12_15m8`
- Purpose: trend/chop + timeframe alignment detector.

2. `syn_rsi_velocity_5m_3bar_z20`
- Purpose: short-horizon oscillator acceleration with macro context.

3. `syn_early_impulse_liq_align_tplus2`
- Purpose: early impulse confirmation from order-book liquidity support.

4. `syn_oi_funding_impulse_tplus2`
- Purpose: participation-vs-crowding confirmation from OI/funding features.

5. `syn_early_momentum_divergence_tplus1`
- Purpose: boundary-price/internal-momentum divergence score.

6. `syn_order_flow_accel_regime_tplus2`
- Purpose: CVD acceleration + order-book pressure + volume regime score.

## Operational Notes
- Backfill floor: `2026-01-22 07:15:00+00`.
- Decision-time legality:
  - `t_plus_1m` scores require `t0+1m` close available.
  - `t_plus_2m` scores require `t0+2m` close available.
- Existing indicator workflows remain untouched.
