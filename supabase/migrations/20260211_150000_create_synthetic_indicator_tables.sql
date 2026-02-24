-- Synthetic indicator subsystem (parallel to existing indicator pipeline).
-- This migration is intentionally isolated and does not modify existing
-- indicators.indicator_configs / indicators.indicator_values / indicators.job_queue.

create schema if not exists indicators;

create table if not exists indicators.synthetic_indicator_configs (
  config_id text primary key,
  indicator_name text not null,
  category text not null default 'synthetic',
  timeframe text not null default '15m',
  decision_phase text not null check (decision_phase in ('t_plus_1m', 't_plus_2m')),
  params jsonb not null default '{}'::jsonb,
  output_columns jsonb not null default '{"v1":"value"}'::jsonb,
  description text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists indicators.synthetic_indicator_values (
  id bigint generated always as identity,
  pair text not null,
  bucket_time timestamptz not null,
  config_id text not null references indicators.synthetic_indicator_configs(config_id) on delete cascade,
  v1 numeric,
  v2 numeric,
  v3 numeric,
  v4 numeric,
  v5 numeric,
  source_time timestamptz,
  computed_at timestamptz not null default now(),
  quality_flags jsonb,
  unique (pair, bucket_time, config_id),
  primary key (id)
);

create index if not exists idx_synthetic_values_pair_bucket
  on indicators.synthetic_indicator_values (pair, bucket_time desc);

create index if not exists idx_synthetic_values_config_pair_bucket
  on indicators.synthetic_indicator_values (config_id, pair, bucket_time desc);

create table if not exists indicators.synthetic_job_queue (
  id bigint generated always as identity primary key,
  pair text not null,
  bucket_time timestamptz not null,
  decision_phase text not null check (decision_phase in ('t_plus_1m', 't_plus_2m')),
  status text not null default 'pending' check (status in ('pending', 'running', 'done', 'failed')),
  attempts integer not null default 0,
  error_message text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  unique (pair, bucket_time, decision_phase)
);

create index if not exists idx_synth_job_status_created
  on indicators.synthetic_job_queue (status, created_at);

comment on table indicators.synthetic_indicator_configs is
  'Configuration catalog for synthetic indicators. Mirrors indicator_configs pattern but remains isolated.';
comment on column indicators.synthetic_indicator_configs.config_id is
  'Stable synthetic indicator identifier (e.g. syn_mtf_signed_efficiency_ratio_5m12_15m8).';
comment on column indicators.synthetic_indicator_configs.indicator_name is
  'Human-readable synthetic indicator name.';
comment on column indicators.synthetic_indicator_configs.category is
  'Synthetic grouping/category for filtering and docs.';
comment on column indicators.synthetic_indicator_configs.timeframe is
  'Primary output timeframe for synthetic value rows (15m event grid).';
comment on column indicators.synthetic_indicator_configs.decision_phase is
  'Earliest legal consumption phase for the synthetic signal: t_plus_1m or t_plus_2m.';
comment on column indicators.synthetic_indicator_configs.params is
  'JSONB of formula constants/lookback windows/threshold metadata.';
comment on column indicators.synthetic_indicator_configs.output_columns is
  'Semantic mapping for v1..v5 outputs.';
comment on column indicators.synthetic_indicator_configs.description is
  'Detailed intent and interpretation notes for this synthetic indicator.';
comment on column indicators.synthetic_indicator_configs.is_active is
  'Whether this synthetic indicator should be computed in active runs.';

comment on table indicators.synthetic_indicator_values is
  'Long-form synthetic indicator values keyed by pair/bucket/config_id.';
comment on column indicators.synthetic_indicator_values.pair is
  'Trading pair (BTC-USD, ETH-USD, SOL-USD).';
comment on column indicators.synthetic_indicator_values.bucket_time is
  '15-minute event boundary (t0).';
comment on column indicators.synthetic_indicator_values.config_id is
  'Synthetic indicator config reference.';
comment on column indicators.synthetic_indicator_values.v1 is
  'Primary synthetic signal score used by filter logic.';
comment on column indicators.synthetic_indicator_values.v2 is
  'Secondary diagnostic component of the synthetic indicator.';
comment on column indicators.synthetic_indicator_values.v3 is
  'Tertiary diagnostic component of the synthetic indicator.';
comment on column indicators.synthetic_indicator_values.v4 is
  'Fourth diagnostic component of the synthetic indicator.';
comment on column indicators.synthetic_indicator_values.v5 is
  'Fifth diagnostic component of the synthetic indicator.';
comment on column indicators.synthetic_indicator_values.source_time is
  'Latest source timestamp used to compute this synthetic row.';
comment on column indicators.synthetic_indicator_values.computed_at is
  'Time when this synthetic row was computed and upserted.';
comment on column indicators.synthetic_indicator_values.quality_flags is
  'JSONB diagnostics (missing inputs, stale order book, low history, etc.).';

comment on table indicators.synthetic_job_queue is
  'Dedicated queue for synthetic computation, isolated from indicators.job_queue.';
comment on column indicators.synthetic_job_queue.decision_phase is
  'Phase-specific scheduling to respect t+1m/t+2m data readiness.';
comment on column indicators.synthetic_job_queue.status is
  'Queue status: pending/running/done/failed.';
comment on column indicators.synthetic_job_queue.attempts is
  'Number of execution attempts for the queued synthetic job.';
comment on column indicators.synthetic_job_queue.error_message is
  'Last error seen while computing this synthetic job.';
